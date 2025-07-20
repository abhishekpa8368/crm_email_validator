{
    'name': ' Crm_Email Validator',
    'version': '1.0',
    'category': 'CRM',
    "author": "Technians",
    'summary': 'Validate email domain via DNS MX record',
    'depends': ['crm'],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_lead_email_validation.xml',
        'views/res_config_setting.xml',

        'data/cron_email_validation.xml',
    ],
    'installable': True,
    'application': False,
}
