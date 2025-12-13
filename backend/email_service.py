import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logger = logging.getLogger(__name__)

def send_verification_email(to_email: str, verification_link: str, smtp_config: dict) -> bool:
    """
    Envoie un email de vérification via SMTP Gmail
    """
    try:
        # Configuration SMTP
        smtp_host = smtp_config.get('smtp_host', 'smtp.gmail.com')
        smtp_port = int(smtp_config.get('smtp_port', 587))
        smtp_user = smtp_config.get('smtp_user', '')
        smtp_password = smtp_config.get('smtp_password', '')
        
        if not smtp_user or not smtp_password:
            logger.error("Configuration SMTP incomplète")
            return False
        
        # Créer le message
        message = MIMEMultipart('alternative')
        message['Subject'] = 'Vérification de votre adresse email - Justification Comptable'
        message['From'] = smtp_user
        message['To'] = to_email
        
        # Corps de l'email en HTML
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #0F172A; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 30px; background-color: #f8f9fa; }}
                .button {{ display: inline-block; padding: 12px 30px; background-color: #0F172A; color: white; text-decoration: none; border-radius: 4px; margin: 20px 0; }}
                .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Justification Comptable</h1>
                </div>
                <div class="content">
                    <h2>Vérifiez votre adresse email</h2>
                    <p>Bonjour,</p>
                    <p>Merci de vous être inscrit sur notre plateforme de justification comptable.</p>
                    <p>Pour activer votre compte, veuillez cliquer sur le bouton ci-dessous :</p>
                    <center>
                        <a href="{verification_link}" class="button">Vérifier mon email</a>
                    </center>
                    <p>Ou copiez ce lien dans votre navigateur :</p>
                    <p style="word-break: break-all; color: #0066cc;">{verification_link}</p>
                    <p><strong>Ce lien est valable pendant 24 heures.</strong></p>
                    <p>Si vous n'avez pas créé de compte, ignorez cet email.</p>
                </div>
                <div class="footer">
                    <p>© 2024 Justification Comptable. Tous droits réservés.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Attacher le corps HTML
        html_part = MIMEText(html_body, 'html')
        message.attach(html_part)
        
        # Envoyer l'email
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(message)
        
        logger.info(f"Email de vérification envoyé à {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de l'email: {e}")
        return False
