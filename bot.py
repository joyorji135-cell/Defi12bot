import os
import tempfile
import logging
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
import requests
from flask import Flask

# Configuration
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GOTENBERG_URL = os.environ.get('GOTENBERG_URL', 'http://localhost:3000')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store user sessions
user_images = {}

# Flask app for Railway health check
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Bot is alive!", 200

@flask_app.route('/health')
def health_check():
    return {"status": "healthy", "bot_running": True}, 200

def run_health_server():
    """Run Flask server to keep Railway happy"""
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

async def start(update: Update, context: CallbackContext):
    """Send welcome message when /start is issued"""
    welcome_text = """
🤖 *Image to PDF Converter Bot*

Send me one or more images, and I'll convert them to a single PDF file!

*How to use:*
1. Send me images (one by one)
2. Type /convert when you're done
3. Or type /cancel to clear all images

*Commands:*
/start - Show this message
/convert - Convert all received images to PDF
/cancel - Clear all images and start over
/help - Show help

*Supported formats:* PNG, JPG, JPEG, GIF, BMP, TIFF, WEBP
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: CallbackContext):
    """Send help message"""
    help_text = """
📚 *How to use this bot:*

1. Send me any image (PNG, JPG, etc.)
2. Send more images if needed
3. Type /convert to create a PDF with all images
4. Type /cancel to clear all saved images

*Tips:*
- Images are kept in order they're received
- Maximum 20 images per session
- All images will be merged into one PDF file
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_image(update: Update, context: CallbackContext):
    """Handle incoming images"""
    user_id = update.effective_user.id
    
    # Initialize user session
    if user_id not in user_images:
        user_images[user_id] = []
    
    # Check limit (max 20 images)
    if len(user_images[user_id]) >= 20:
        await update.message.reply_text(
            "⚠️ Maximum 20 images per session. Type /convert to create PDF or /cancel to clear."
        )
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text("📥 Downloading image...")
    
    try:
        # Get the image file
        photo = update.message.photo[-1]  # Get highest quality
        file = await context.bot.get_file(photo.file_id)
        
        # Download to temp file
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            await file.download_to_drive(temp_file.name)
            user_images[user_id].append(temp_file.name)
        
        # Show progress
        keyboard = [
            [
                InlineKeyboardButton("✅ Convert Now", callback_data='convert'),
                InlineKeyboardButton("❌ Cancel", callback_data='cancel')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await processing_msg.delete()
        await update.message.reply_text(
            f"✅ Image received! ({len(user_images[user_id])}/20 images saved)\n\n"
            f"Send more images or click a button below:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error downloading image: {str(e)}")
        await processing_msg.edit_text(f"❌ Failed to download image: {str(e)}")

async def button_callback(update: Update, context: CallbackContext):
    """Handle inline button clicks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == 'convert':
        # Simulate convert command
        await convert_command(update, context)
    elif query.data == 'cancel':
        await cancel_command(update, context)
    
    try:
        await query.message.delete()
    except:
        pass

async def convert_command(update: Update, context: CallbackContext):
    """Convert images to PDF"""
    user_id = update.effective_user.id
    
    # Check if user has images
    if user_id not in user_images or not user_images[user_id]:
        await update.message.reply_text("❌ No images found. Send me some images first!")
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text("🔄 Converting images to PDF... Please wait.")
    
    try:
        # Prepare files for Gotenberg
        gotenberg_files = []
        for idx, img_path in enumerate(user_images[user_id]):
            with open(img_path, 'rb') as f:
                gotenberg_files.append(
                    ('files', (f'image_{idx+1}.jpg', f, 'image/jpeg'))
                )
        
        # Send to Gotenberg
        response = requests.post(
            f"{GOTENBERG_URL}/forms/libreoffice/convert",
            files=gotenberg_files,
            timeout=60
        )
        
        if response.status_code == 200:
            # Send PDF back to user
            await update.message.reply_document(
                document=response.content,
                filename='converted.pdf',
                caption=f"✅ PDF created successfully!\n📄 Pages: {len(user_images[user_id])}\n🖼️ Images converted: {len(user_images[user_id])}"
            )
            await processing_msg.delete()
        else:
            await processing_msg.edit_text(f"❌ Conversion failed: {response.text}")
        
    except Exception as e:
        logger.error(f"Conversion error: {str(e)}")
        await processing_msg.edit_text(f"❌ Error: {str(e)}")
    
    finally:
        # Clean up temp files
        for img_path in user_images.get(user_id, []):
            try:
                os.unlink(img_path)
            except:
                pass
        user_images[user_id] = []

async def cancel_command(update: Update, context: CallbackContext):
    """Clear all images for user"""
    user_id = update.effective_user.id
    
    if user_id in user_images:
        # Clean up temp files
        for img_path in user_images[user_id]:
            try:
                os.unlink(img_path)
            except:
                pass
        user_images[user_id] = []
    
    await update.message.reply_text("🗑️ All images cleared! Send me new images when you're ready.")

async def error_handler(update: Update, context: CallbackContext):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An error occurred. Please try again or type /start"
        )

def main():
    """Start the bot"""
    # Validate token
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable not set!")
        return
    
    logger.info(f"Bot token found (length: {len(TELEGRAM_TOKEN)})")
    logger.info(f"Gotenberg URL: {GOTENBERG_URL}")
    
    # Start health check server in background
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info("Health check server started on port 8080")
    
    try:
        # Create application
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("convert", convert_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(MessageHandler(filters.PHOTO, handle_image))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_error_handler(error_handler)
        
        # Start bot
        logger.info("Bot started successfully! Listening for messages...")
        print("Bot is running...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Failed to start bot: {str(e)}")
        print(f"ERROR: {str(e)}")

if __name__ == '__main__':
    main()
