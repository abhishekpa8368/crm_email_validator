from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'


    email_verification_method = fields.Selection([
        ('library', 'Library DNS Verification'),
        ('api', 'Comming Soon'),
    ], string='Email Verification Method', default='library', config_parameter='email_validation.method')

    # Fields for Email Validation Settings
    check_email_syntax = fields.Boolean(string="Check Email Syntax",
                                        config_parameter='email_validation.check_email_syntax')
    check_dns = fields.Boolean(string="Check DNS of Domain", config_parameter='email_validation.check_dns')
    check_smtp = fields.Boolean(string="Check SMTP Verification", config_parameter='email_validation.check_smtp')

    # API Key for API-based verification method
    api_key = fields.Char(string="API Key", config_parameter='email_validation.api_key')

    @api.model
    def set_values(self):
        # This method will be triggered when saving settings from the configuration form
        super(ResConfigSettings, self).set_values()

        # Save values for all fields defined in the model (especially for API Key)
        self.env['ir.config_parameter'].set_param('email_validation.api_key', self.api_key)
        self.env['ir.config_parameter'].set_param('email_validation.method', self.email_verification_method)
        self.env['ir.config_parameter'].set_param('email_validation.check_email_syntax', self.check_email_syntax)
        self.env['ir.config_parameter'].set_param('email_validation.check_dns', self.check_dns)
        self.env['ir.config_parameter'].set_param('email_validation.check_smtp', self.check_smtp)

    @api.model
    def get_values(self):
        # This method will load the values when entering the settings form
        res = super(ResConfigSettings, self).get_values()
        params = self.env['ir.config_parameter'].sudo()

        # Load the stored values into the settings form fields
        res.update({
            'email_verification_method': params.get_param('email_validation.method', default='library'),
            'check_email_syntax': params.get_param('email_validation.check_email_syntax', default=False),
            'check_dns': params.get_param('email_validation.check_dns', default=False),
            'check_smtp': params.get_param('email_validation.check_smtp', default=False),
            'api_key': params.get_param('email_validation.api_key', default=''),
        })
        return res
