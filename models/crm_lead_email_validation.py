import logging
import re
import smtplib
import socket
import dns.resolver

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    is_email_valid = fields.Boolean(string='Email Valid', compute='_compute_is_email_valid', store=True)
    email_validation_message = fields.Char(string='Email Validation Message')
    show_validate_email_button = fields.Boolean(string="Show Validate Email Button", compute='_compute_show_validate_email_button')

    @api.depends('email_from')
    def _compute_is_email_valid(self):
        for record in self:
            record.is_email_valid = False
            record.email_validation_message = False

            try:
                if not record.email_from:
                    record.email_validation_message = "No email provided"
                    continue

                config = self.env['res.config.settings'].sudo().get_values()

                if config.get('check_email_syntax', False):
                    self._validate_email_format(record.email_from)

                domain = self._extract_domain(record.email_from)

                if config.get('check_dns', False):
                    self._get_mx_record(domain)

                record.email_validation_message = "Ready for SMTP Check"

            except Exception as e:
                error_message = str(e)
                _logger.warning(f"Validation error for {record.email_from}: {error_message}")
                record.email_validation_message = error_message

    @api.depends('email_from', 'email_validation_message')
    def _compute_show_validate_email_button(self):
        for rec in self:
            config = self.env['res.config.settings'].sudo().get_values()
            rec.show_validate_email_button = False
            if config.get('check_email_syntax') and config.get('check_dns') and config.get('check_smtp'):
                if rec.email_validation_message == "Ready for SMTP Check":
                    rec.show_validate_email_button = True

    def action_validate_email_smtp(self):
        for record in self:
            try:
                domain = self._extract_domain(record.email_from)
                mx_record = self._get_mx_record(domain)

                # Check if Port 25 is open before attempting SMTP
                port_ok, port_error = self._check_port_25_open(mx_record)
                if not port_ok:
                    raise UserError(f"SMTP Validation Failed: {port_error}")

                result, smtp_error = self._smtp_check(record.email_from, mx_record)

                if result:
                    record.email_validation_message = "Valid Email"
                    record.is_email_valid = True
                else:
                    record.email_validation_message = smtp_error or "User Does Not Exist"
                    record.is_email_valid = False
                    raise UserError(f"SMTP Validation Failed: {smtp_error or 'Unknown error'}")

            except Exception as e:
                raise UserError(f"SMTP Validation Failed: {e}")

    def _validate_email_format(self, email):
        email = email.strip()
        regex = r"^[a-zA-Z0-9]+(\.?[a-zA-Z0-9]+)*@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$"
        if not re.match(regex, email):
            raise ValueError("Syntax Error: Invalid email format")
        local_part, _ = email.split('@', 1)
        if '-' in local_part or '_' in local_part:
            raise ValueError("Syntax Error: '-' and '_' are not allowed in local part")

    def _extract_domain(self, email):
        if '@' not in email:
            raise ValueError("Syntax Error: Missing '@'")
        return email.split('@')[1]

    def _get_mx_record(self, domain):
        try:
            answers = dns.resolver.resolve(domain, 'MX')
            return str(answers[0].exchange).rstrip('.')
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            raise ValueError(f"Domain not Exist: {domain}")

    def _check_port_25_open(self, mx_record):
        """ Check if port 25 is open and reachable """
        try:
            sock = socket.create_connection((mx_record, 25), timeout=5)
            sock.close()
            return True, None
        except socket.timeout:
            return False, "Connection timed out — Port 25 likely blocked by AWS"
        except Exception as e:
            return False, f"Port 25 test failed: {e}"

    def _smtp_check(self, email, mx_record):
        """ Perform the SMTP validation """
        try:
            server = smtplib.SMTP(timeout=10)
            server.connect(mx_record, 25)
            server.helo()
            server.mail('test@example.com')
            code, _ = server.rcpt(email)
            server.quit()
            return code in (250, 251), None
        except smtplib.SMTPConnectError as e:
            return False, f"SMTP Connect Error: {e}"
        except smtplib.SMTPServerDisconnected:
            return False, "SMTP Server Disconnected"
        except smtplib.SMTPRecipientsRefused:
            return False, "Recipient refused"
        except smtplib.SMTPException as e:
            return False, f"SMTP Error: {e}"
        except OSError as e:
            if "timed out" in str(e):
                return False, "Connection timed out (Possible port 25 block on AWS)"
            elif "Network is unreachable" in str(e):
                return False, "Network unreachable - check firewall"
            else:
                return False, f"OS Error: {e}"
        except Exception as e:
            return False, f"Unknown SMTP Error: {e}"

    def cron_validate_all_emails(self):
        leads = self.search([('email_from', '!=', False)])
        config = self.env['res.config.settings'].sudo().get_values()

        for lead in leads:
            try:
                lead.is_email_valid = False
                lead.email_validation_message = False

                email = lead.email_from.strip()

                if config.get('check_email_syntax', False):
                    self._validate_email_format(email)

                domain = self._extract_domain(email)

                if config.get('check_dns', False):
                    mx_record = self._get_mx_record(domain)
                else:
                    mx_record = None

                # Do SMTP if setting is enabled and DNS was successful
                if config.get('check_smtp', False) and mx_record:
                    result, smtp_error = self._smtp_check(email, mx_record)
                    lead.is_email_valid = result
                    lead.email_validation_message = smtp_error or "Valid Email"
                else:
                    lead.email_validation_message = "Ready for SMTP Check" if mx_record else "DNS Skipped"

            except Exception as e:
                _logger.warning(f"Validation error for {lead.email_from}: {e}")
                lead.email_validation_message = str(e)

            # Always recompute button visibility
            lead._compute_show_validate_email_button()

    def action_bulk_validate_email(self):
        config = self.env['res.config.settings'].sudo().get_values()

        for lead in self:
            try:
                lead.is_email_valid = False
                lead.email_validation_message = False

                if not lead.email_from:
                    lead.email_validation_message = "No email provided"
                    continue

                email = lead.email_from.strip()

                if config.get('check_email_syntax', False):
                    self._validate_email_format(email)

                domain = self._extract_domain(email)

                mx_record = None
                if config.get('check_dns', False):
                    mx_record = self._get_mx_record(domain)

                if config.get('check_smtp', False) and mx_record:
                    result, smtp_error = self._smtp_check(email, mx_record)
                    lead.is_email_valid = result
                    lead.email_validation_message = smtp_error or "Valid Email"
                else:
                    lead.email_validation_message = "Ready for SMTP Check" if mx_record else "DNS Skipped"

            except Exception as e:
                _logger.warning(f"Bulk validation error for {lead.email_from}: {e}")
                lead.email_validation_message = str(e)

            lead._compute_show_validate_email_button()






# import logging
# import re
# import smtplib
# import dns.resolver

# from odoo import models, fields, api
# from odoo.exceptions import UserError

# _logger = logging.getLogger(__name__)

# class CrmLead(models.Model):
#     _inherit = 'crm.lead'

#     is_email_valid = fields.Boolean(string='Email Valid', compute='_compute_is_email_valid', store=True)
#     email_validation_message = fields.Char(string='Email Validation Message')
#     show_validate_email_button = fields.Boolean(string="Show Validate Email Button", compute='_compute_show_validate_email_button')

#     @api.depends('email_from')
#     def _compute_is_email_valid(self):
#         for record in self:
#             record.is_email_valid = False
#             record.email_validation_message = False

#             try:
#                 if not record.email_from:
#                     record.email_validation_message = "No email provided"
#                     continue

#                 config = self.env['res.config.settings'].sudo().get_values()

#                 if config.get('check_email_syntax', False):
#                     self._validate_email_format(record.email_from)

#                 domain = self._extract_domain(record.email_from)

#                 if config.get('check_dns', False):
#                     self._get_mx_record(domain)

#                 record.email_validation_message = "Ready for SMTP Check"

#             except Exception as e:
#                 error_message = str(e)
#                 _logger.warning(f"Validation error for {record.email_from}: {error_message}")
#                 record.email_validation_message = error_message

#     @api.depends('email_from', 'email_validation_message')
#     def _compute_show_validate_email_button(self):
#         for rec in self:
#             config = self.env['res.config.settings'].sudo().get_values()
#             rec.show_validate_email_button = False
#             if config.get('check_email_syntax') and config.get('check_dns') and config.get('check_smtp'):
#                 if rec.email_validation_message == "Ready for SMTP Check":
#                     rec.show_validate_email_button = True

#     def action_validate_email_smtp(self):
#         for record in self:
#             try:
#                 domain = self._extract_domain(record.email_from)
#                 mx_record = self._get_mx_record(domain)
#                 result = self._smtp_check(record.email_from, mx_record)
#                 if not result:
#                     record.email_validation_message = "User Does Not Exist"
#                     record.is_email_valid = False
#                 else:
#                     record.email_validation_message = "Valid Email"
#                     record.is_email_valid = True
#             except Exception as e:
#                 raise UserError(f"SMTP Validation Failed: {e}")

#     def _validate_email_format(self, email):
#         email = email.strip()
#         regex = r"^[a-zA-Z0-9]+(\.?[a-zA-Z0-9]+)*@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$"
#         if not re.match(regex, email):
#             raise ValueError("Syntax Error: Invalid email format")
#         local_part, _ = email.split('@', 1)
#         if '-' in local_part or '_' in local_part:
#             raise ValueError("Syntax Error: '-' and '_' are not allowed in local part")

#     def _extract_domain(self, email):
#         if '@' not in email:
#             raise ValueError("Syntax Error: Missing '@'")
#         return email.split('@')[1]

#     def _get_mx_record(self, domain):
#         try:
#             answers = dns.resolver.resolve(domain, 'MX')
#             return str(answers[0].exchange).rstrip('.')
#         except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
#             raise ValueError(f"Domain not Exist: {domain}")

#     def _smtp_check(self, email, mx_record):
#         try:
#             server = smtplib.SMTP(timeout=10)
#             server.connect(mx_record, 25)
#             server.helo()
#             server.mail('test@example.com')
#             code, _ = server.rcpt(email)
#             server.quit()
#             return code in (250, 251)
#         except Exception as e:
#             _logger.warning(f"SMTP check failed for {email}: {e}")
#             return False

#     def cron_validate_all_emails(self):
#         leads = self.search([('email_from', '!=', False)])
#         config = self.env['res.config.settings'].sudo().get_values()

#         for lead in leads:
#             try:
#                 lead.is_email_valid = False
#                 lead.email_validation_message = False

#                 email = lead.email_from.strip()

#                 if config.get('check_email_syntax', False):
#                     self._validate_email_format(email)

#                 domain = self._extract_domain(email)

#                 if config.get('check_dns', False):
#                     mx_record = self._get_mx_record(domain)
#                 else:
#                     mx_record = None

#                 # Do SMTP if setting is enabled and DNS was successful
#                 if config.get('check_smtp', False) and mx_record:
#                     result = self._smtp_check(email, mx_record)
#                     if result:
#                         lead.is_email_valid = True
#                         lead.email_validation_message = "Valid Email"
#                     else:
#                         lead.email_validation_message = "User Does Not Exist"
#                 else:
#                     lead.email_validation_message = "Ready for SMTP Check" if mx_record else "DNS Skipped"

#             except Exception as e:
#                 _logger.warning(f"Validation error for {lead.email_from}: {e}")
#                 lead.email_validation_message = str(e)

#             # Always recompute button visibility
#             lead._compute_show_validate_email_button()

#     def action_bulk_validate_email(self):
#         config = self.env['res.config.settings'].sudo().get_values()

#         for lead in self:
#             try:
#                 lead.is_email_valid = False
#                 lead.email_validation_message = False

#                 if not lead.email_from:
#                     lead.email_validation_message = "No email provided"
#                     continue

#                 email = lead.email_from.strip()

#                 if config.get('check_email_syntax', False):
#                     self._validate_email_format(email)

#                 domain = self._extract_domain(email)

#                 mx_record = None
#                 if config.get('check_dns', False):
#                     mx_record = self._get_mx_record(domain)

#                 if config.get('check_smtp', False) and mx_record:
#                     result = self._smtp_check(email, mx_record)
#                     lead.is_email_valid = result
#                     lead.email_validation_message = "Valid Email" if result else "User Does Not Exist"
#                 else:
#                     lead.email_validation_message = "Ready for SMTP Check" if mx_record else "DNS Skipped"

#             except Exception as e:
#                 _logger.warning(f"Bulk validation error for {lead.email_from}: {e}")
#                 lead.email_validation_message = str(e)

#             lead._compute_show_validate_email_button()






