import os
import re
import io
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
REMOVE_BG_API_KEY = os.getenv("REMOVE_BG_API_KEY")

TIMEOUT = 20
RESULTS_PER_PAGE = 5

# Store each user's current search session
USER_SEARCHES = {}

# Store which feature the user is using
USER_MODES = {}


# ==========================================
# QUERY PARSER
# ==========================================

def parse_query(text):

    original = text.strip()
    lower = original.lower()

    device = "any"
    quality = "normal"

    mobile_words = [
        "mobile",
        "phone",
        "smartphone",
        "iphone",
        "android",
        "portrait",
        "vertical",
    ]

    desktop_words = [
        "laptop",
        "desktop",
        "pc",
        "computer",
        "monitor",
        "landscape",
        "wide",
    ]

    quality_words = [
        "4k",
        "uhd",
        "2160p",
        "ultra hd",
    ]

    if any(
        re.search(
            r"\b" + re.escape(word) + r"\b",
            lower
        )
        for word in mobile_words
    ):
        device = "mobile"

    elif any(
        re.search(
            r"\b" + re.escape(word) + r"\b",
            lower
        )
        for word in desktop_words
    ):
        device = "desktop"

    if any(
        word in lower
        for word in quality_words
    ):
        quality = "4k"

    remove_words = (
        mobile_words
        + desktop_words
        + quality_words
        + [
            "wallpaper",
            "wallpapers",
            "wall",
            "background",
            "backgrounds",
            "hd",
            "fhd",
            "full hd",
            "for",
            "me",
            "please",
        ]
    )

    query = original

    for word in sorted(
        remove_words,
        key=len,
        reverse=True
    ):

        query = re.sub(
            r"\b" + re.escape(word) + r"\b",
            " ",
            query,
            flags=re.IGNORECASE
        )

    query = re.sub(
        r"\s+",
        " ",
        query
    ).strip()

    return query, device, quality


# ==========================================
# IMAGE QUALITY / RATIO FILTER
# ==========================================

def suitable_image(
    item,
    device,
    quality
):

    width = item.get(
        "original_width"
    )

    height = item.get(
        "original_height"
    )

    try:
        width = int(width)
        height = int(height)

    except:
        return False

    if width <= 0 or height <= 0:
        return False

    ratio = width / height

    if device == "mobile":

        if height <= width:
            return False

        if ratio < 0.40 or ratio > 0.80:
            return False

        if height < 1200:
            return False

        if (
            quality == "4k"
            and height < 1800
        ):
            return False

        return True

    if device == "desktop":

        if width <= height:
            return False

        if ratio < 1.30 or ratio > 2.40:
            return False

        if width < 1400:
            return False

        if (
            quality == "4k"
            and width < 2500
        ):
            return False

        return True

    if min(width, height) < 900:
        return False

    if (
        quality == "4k"
        and max(width, height) < 2500
    ):
        return False

    return True


# ==========================================
# PNG IMAGE FILTER
# ==========================================

def suitable_png(item):

    width = item.get(
        "original_width"
    )

    height = item.get(
        "original_height"
    )

    try:
        width = int(width)
        height = int(height)

    except:
        return False

    if width <= 0 or height <= 0:
        return False

    # Avoid extremely small images
    if max(width, height) < 500:
        return False

    original = str(
        item.get("original", "")
    ).lower()

    title = str(
        item.get("title", "")
    ).lower()

    source = str(
        item.get("source", "")
    ).lower()

    link = str(
        item.get("link", "")
    ).lower()

    combined = (
        original
        + " "
        + title
        + " "
        + source
        + " "
        + link
    )

    # Strong PNG signals
    png_signals = [
        ".png",
        "png",
        "transparent",
        "no background",
        "cutout",
        "render",
    ]

    if any(
        word in combined
        for word in png_signals
    ):
        return True

    # If no clear PNG signal, still allow
    # reasonably large images because Google
    # may not expose the file extension.
    if min(width, height) >= 700:
        return True

    return False


# ==========================================
# GOOGLE IMAGES SEARCH - WALLPAPERS
# ==========================================

def google_images_search(
    query,
    device,
    quality,
    page
):

    search_query = query + " wallpaper"

    if device == "mobile":
        search_query += " mobile portrait"

    elif device == "desktop":
        search_query += " desktop landscape"

    if quality == "4k":
        search_query += " 4K"

    params = {
        "engine": "google_images",
        "q": search_query,
        "api_key": SERPAPI_KEY,
        "safe": "active",
        "hl": "en",
        "gl": "us",
        "ijn": page,
    }

    try:

        response = requests.get(
            "https://serpapi.com/search",
            params=params,
            timeout=TIMEOUT
        )

        if response.status_code != 200:
            print(
                "SerpApi HTTP:",
                response.status_code
            )
            return []

        data = response.json()

    except Exception as e:

        print(
            "SerpApi error:",
            e
        )

        return []

    return data.get(
        "images_results",
        []
    )


# ==========================================
# GOOGLE IMAGES SEARCH - PNG
# ==========================================

def google_png_search(
    query,
    page
):

    search_query = (
        query
        + " PNG transparent background"
    )

    params = {
        "engine": "google_images",
        "q": search_query,
        "api_key": SERPAPI_KEY,
        "safe": "active",
        "hl": "en",
        "gl": "us",
        "ijn": page,
    }

    try:

        response = requests.get(
            "https://serpapi.com/search",
            params=params,
            timeout=TIMEOUT
        )

        if response.status_code != 200:

            print(
                "SerpApi PNG HTTP:",
                response.status_code
            )

            return []

        data = response.json()

    except Exception as e:

        print(
            "SerpApi PNG error:",
            e
        )

        return []

    return data.get(
        "images_results",
        []
    )


# ==========================================
# COLLECT WALLPAPER RESULTS
# ==========================================

def collect_results(
    query,
    device,
    quality,
    start_page=0
):

    collected = []

    for page in range(
        start_page,
        start_page + 3
    ):

        images = google_images_search(
            query,
            device,
            quality,
            page
        )

        for item in images:

            url = item.get(
                "original"
            )

            if not url:
                continue

            if not suitable_image(
                item,
                device,
                quality
            ):
                continue

            collected.append(item)

    return collected


# ==========================================
# COLLECT PNG RESULTS
# ==========================================

def collect_png_results(
    query,
    start_page=0
):

    collected = []

    for page in range(
        start_page,
        start_page + 3
    ):

        images = google_png_search(
            query,
            page
        )

        for item in images:

            url = item.get(
                "original"
            )

            if not url:
                continue

            if not suitable_png(item):
                continue

            collected.append(item)

    return collected


# ==========================================
# DUPLICATE FILTER
# ==========================================

def remove_duplicates(
    items,
    seen
):

    final = []

    local_seen = set(seen)

    for item in items:

        url = item.get(
            "original"
        )

        if not url:
            continue

        key = (
            url
            .split("?")[0]
            .lower()
            .strip()
        )

        if key in local_seen:
            continue

        local_seen.add(key)

        final.append(item)

    return final


# ==========================================
# REMOVE BACKGROUND API
# ==========================================

def remove_background(image_bytes):

    if not REMOVE_BG_API_KEY:
        return None, "API key is missing."

    try:

        response = requests.post(
            "https://api.remove.bg/v1.0/removebg",
            files={
                "image_file": (
                    "image.jpg",
                    image_bytes,
                    "image/jpeg"
                )
            },
            data={
                "size": "auto",
                "format": "png"
            },
            headers={
                "X-Api-Key": REMOVE_BG_API_KEY
            },
            timeout=60
        )

        if response.status_code == 200:
            return response.content, None

        print(
            "Remove.bg HTTP:",
            response.status_code,
            response.text[:500]
        )

        return None, (
            f"Remove.bg error "
            f"{response.status_code}"
        )

    except Exception as e:

        print(
            "Remove.bg request error:",
            e
        )

        return None, str(e)


# ==========================================
# SEND NEXT 5 WALLPAPERS
# ==========================================

async def send_five(
    context,
    user_id,
    chat_id
):

    data = USER_SEARCHES.get(
        user_id
    )

    if not data:
        return

    query = data["query"]
    device = data["device"]
    quality = data["quality"]

    results = data["results"]
    index = data["index"]

    sent = 0

    while sent < RESULTS_PER_PAGE:

        if index >= len(results):

            next_page = data[
                "next_page"
            ]

            new_results = collect_results(
                query,
                device,
                quality,
                next_page
            )

            new_results = remove_duplicates(
                new_results,
                data["seen"]
            )

            data["next_page"] += 3

            results.extend(
                new_results
            )

            if not new_results:
                break

        if index >= len(results):
            break

        item = results[index]

        index += 1

        url = item.get(
            "original"
        )

        if not url:
            continue

        key = (
            url
            .split("?")[0]
            .lower()
            .strip()
        )

        if key in data["seen"]:
            continue

        try:

            width = item.get(
                "original_width",
                "?"
            )

            height = item.get(
                "original_height",
                "?"
            )

            caption = (
                f"🖼️ {query}\n"
                f"📐 {width}×{height}"
            )

            await context.bot.send_photo(
                chat_id=chat_id,
                photo=url,
                caption=caption
            )

            data["seen"].add(key)

            sent += 1

        except Exception as e:

            print(
                "Telegram image error:",
                e
            )

            continue

    data["index"] = index

    if (
        index < len(results)
        or data["next_page"] < 12
    ):

        keyboard = [
            [
                InlineKeyboardButton(
                    "➕ More 5",
                    callback_data="more5"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="main_menu"
                )
            ]
        ]

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Want to explore more "
                "wallpapers?"
            ),
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

    else:

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ No more suitable "
                "results are available."
            )
        )


# ==========================================
# SEND NEXT 5 PNGs
# ==========================================

async def send_png_five(
    context,
    user_id,
    chat_id
):

    data = USER_SEARCHES.get(
        user_id
    )

    if not data:
        return

    query = data["query"]

    results = data["results"]
    index = data["index"]

    sent = 0

    while sent < RESULTS_PER_PAGE:

        if index >= len(results):

            next_page = data[
                "next_page"
            ]

            new_results = collect_png_results(
                query,
                next_page
            )

            new_results = remove_duplicates(
                new_results,
                data["seen"]
            )

            data["next_page"] += 3

            results.extend(
                new_results
            )

            if not new_results:
                break

        if index >= len(results):
            break

        item = results[index]

        index += 1

        url = item.get(
            "original"
        )

        if not url:
            continue

        key = (
            url
            .split("?")[0]
            .lower()
            .strip()
        )

        if key in data["seen"]:
            continue

        try:

            width = item.get(
                "original_width",
                "?"
            )

            height = item.get(
                "original_height",
                "?"
            )

            caption = (
                f"🖼️ PNG: {query}\n"
                f"📐 {width}×{height}\n"
                f"✨ Transparent PNG search"
            )

            await context.bot.send_document(
                chat_id=chat_id,
                document=url,
                caption=caption
            )

            data["seen"].add(key)

            sent += 1

        except Exception as e:

            print(
                "Telegram PNG error:",
                e
            )

            # Some servers don't allow
            # Telegram to download the
            # original URL as document.
            # Try sending as photo instead.

            try:

                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=url,
                    caption=(
                        f"🖼️ PNG: {query}\n"
                        f"📐 {width}×{height}"
                    )
                )

                data["seen"].add(key)

                sent += 1

            except Exception as e2:

                print(
                    "Telegram PNG photo error:",
                    e2
                )

                continue

    data["index"] = index

    if (
        index < len(results)
        or data["next_page"] < 12
    ):

        keyboard = [
            [
                InlineKeyboardButton(
                    "➕ More 5",
                    callback_data="png_more5"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="main_menu"
                )
            ]
        ]

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Want more PNG images?"
            ),
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

    else:

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ No more suitable "
                "PNG results are available."
            )
        )


# ==========================================
# MAIN MENU
# ==========================================

async def show_main_menu(
    update,
    context,
    edit=False
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🖼️ Wallpaper Search",
                callback_data="wallpaper_mode"
            )
        ],
        [
            InlineKeyboardButton(
                "🖼️ PNG Images",
                callback_data="png_mode"
            )
        ],
        [
            InlineKeyboardButton(
                "✂️ Remove Background",
                callback_data="remove_bg_mode"
            )
        ],
    ]

    text = (
        "✨ FHD Wallpapers Bot\n\n"
        "Choose what you want to search:\n\n"
        "🖼️ Wallpaper Search\n"
        "Search HD & 4K wallpapers.\n\n"
        "🖼️ PNG Images\n"
        "Search PNG & transparent images.\n\n"
        "✂️ Remove Background\n"
        "Remove photo background and get a transparent PNG."
    )

    if edit:

        await update.callback_query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )


# ==========================================
# START
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    USER_MODES[user_id] = "wallpaper"

    await show_main_menu(
        update,
        context
    )


# ==========================================
# REMOVE BACKGROUND PHOTO HANDLER
# ==========================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    mode = USER_MODES.get(
        user_id,
        "wallpaper"
    )

    if mode != "remove_bg":
        return

    status = await update.message.reply_text(
        "✂️ Removing background...\n\n"
        "⏳ Please wait."
    )

    try:

        photo = update.message.photo[-1]

        telegram_file = await context.bot.get_file(
            photo.file_id
        )

        image_bytes = await telegram_file.download_as_bytearray()

        result, error = remove_background(
            bytes(image_bytes)
        )

        if not result:

            await status.edit_text(
                "❌ Background removal failed.\n\n"
                f"Reason: {error}"
            )

            return

        await status.edit_text(
            "✅ Background removed!\n\n"
            "📤 Sending transparent PNG..."
        )

        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(result),
            filename="no_background.png",
            caption=(
                "✂️ Background Removed\n"
                "✨ Transparent PNG"
            )
        )

        await status.delete()

        keyboard = [
            [
                InlineKeyboardButton(
                    "✂️ Remove Another",
                    callback_data="remove_bg_mode"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Main Menu",
                    callback_data="main_menu"
                )
            ]
        ]

        await context.bot.send_message(
            chat_id=chat_id,
            text="What would you like to do next?",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

    except Exception as e:

        print(
            "Remove background handler error:",
            e
        )

        await status.edit_text(
            "❌ Something went wrong.\n\n"
            "Please try another photo."
        )


# ==========================================
# NORMAL TEXT MESSAGE
# ==========================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    if not text:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    mode = USER_MODES.get(
        user_id,
        "wallpaper"
    )

    # ======================================
    # PNG MODE
    # ======================================

    if mode == "png":

        query = re.sub(
            r"\bpng\b",
            " ",
            text,
            flags=re.IGNORECASE
        )

        query = re.sub(
            r"\s+",
            " ",
            query
        ).strip()

        if not query:

            await update.message.reply_text(
                "❌ Please enter what PNG "
                "you want.\n\n"
                "Example:\n"
                "• hand png\n"
                "• anime hair png\n"
                "• car png"
            )

            return

        status = await update.message.reply_text(

            f"🔎 Searching PNGs for: {query}\n\n"
            f"⏳ Finding transparent images..."
        )

        USER_SEARCHES[user_id] = {

            "query": query,

            "device": "any",

            "quality": "normal",

            "results": [],

            "index": 0,

            "next_page": 0,

            "seen": set(),

            "type": "png",
        }

        data = USER_SEARCHES[user_id]

        results = collect_png_results(
            query,
            0
        )

        results = remove_duplicates(
            results,
            set()
        )

        data["results"] = results
        data["next_page"] = 3

        if not results:

            await status.edit_text(

                f"❌ No suitable PNGs found "
                f"for '{query}'.\n\n"
                f"Try another search."
            )

            del USER_SEARCHES[user_id]

            return

        await status.edit_text(

            f"✅ PNGs found for: {query}\n\n"
            f"🖼️ Sending the best 5..."
        )

        await send_png_five(
            context,
            user_id,
            chat_id
        )

        return

    # ======================================
    # WALLPAPER MODE
    # ======================================

    query, device, quality = parse_query(
        text
    )

    if not query:

        await update.message.reply_text(
            "❌ Please enter a subject "
            "to search for."
        )

        return

    device_text = {
        "mobile": "📱 Mobile",
        "desktop": "💻 Desktop",
        "any": "🖼️ Any format",
    }[device]

    quality_text = {
        "normal": "✨ High Quality",
        "4k": "🔥 4K Preferred",
    }[quality]

    status = await update.message.reply_text(

        f"🔎 Searching for: {query}\n"
        f"{device_text}\n"
        f"{quality_text}\n\n"
        f"⏳ Finding the best wallpapers..."
    )

    USER_SEARCHES[user_id] = {

        "query": query,

        "device": device,

        "quality": quality,

        "results": [],

        "index": 0,

        "next_page": 0,

        "seen": set(),

        "type": "wallpaper",
    }

    data = USER_SEARCHES[user_id]

    results = collect_results(
        query,
        device,
        quality,
        0
    )

    results = remove_duplicates(
        results,
        set()
    )

    data["results"] = results
    data["next_page"] = 3

    if not results:

        await status.edit_text(

            f"❌ No suitable wallpapers "
            f"were found for '{query}'.\n\n"
            f"Try another search term."
        )

        del USER_SEARCHES[user_id]

        return

    await status.edit_text(

        f"✅ Wallpapers found for: "
        f"{query}\n\n"
        f"{device_text}\n"
        f"{quality_text}\n\n"
        f"🖼️ Sending the best 5..."
    )

    await send_five(
        context,
        user_id,
        chat_id
    )


# ==========================================
# CALLBACK BUTTONS
# ==========================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id
    chat_id = query.message.chat_id

    # --------------------------------------
    # Wallpaper mode
    # --------------------------------------

    if query.data == "wallpaper_mode":

        USER_MODES[user_id] = "wallpaper"

        await query.message.edit_text(

            "🖼️ Wallpaper Search Mode\n\n"
            "Now type anything you want "
            "to search for.\n\n"
            "Examples:\n"
            "• Ferrari 4K\n"
            "• Tokyo night mobile\n"
            "• Space wallpaper\n\n"
            "🚀 Send your search:"
        )

        return

    # --------------------------------------
    # PNG mode
    # --------------------------------------

    if query.data == "png_mode":

        USER_MODES[user_id] = "png"

        await query.message.edit_text(

            "🖼️ PNG Search Mode\n\n"
            "Type anything you want as a PNG.\n\n"
            "Examples:\n"
            "• hand png\n"
            "• anime hair png\n"
            "• car png\n"
            "• Naruto png\n"
            "• flower png\n\n"
            "🚀 Send your PNG search:"
        )

        return

    # --------------------------------------
    # Remove Background mode
    # --------------------------------------

    if query.data == "remove_bg_mode":

        USER_MODES[user_id] = "remove_bg"

        await query.message.edit_text(
            "✂️ Remove Background Mode\n\n"
            "Send me a photo and I will remove "
            "its background.\n\n"
            "✨ You will receive a transparent PNG.\n\n"
            "📸 Send your photo:"
        )

        return

    # --------------------------------------
    # Main menu
    # --------------------------------------

    if query.data == "main_menu":

        USER_MODES[user_id] = "wallpaper"

        USER_SEARCHES.pop(
            user_id,
            None
        )

        await show_main_menu(
            update,
            context,
            edit=True
        )

        return

    # --------------------------------------
    # More wallpapers
    # --------------------------------------

    if query.data == "more5":

        if user_id not in USER_SEARCHES:

            await query.message.reply_text(

                "⚠️ This search session "
                "has expired.\n\n"
                "Please start a new search."
            )

            return

        await query.answer(
            "Finding 5 different wallpapers..."
        )

        await send_five(
            context,
            user_id,
            chat_id
        )

        return

    # --------------------------------------
    # More PNGs
    # --------------------------------------

    if query.data == "png_more5":

        if user_id not in USER_SEARCHES:

            await query.message.reply_text(

                "⚠️ This search session "
                "has expired.\n\n"
                "Please start a new PNG search."
            )

            return

        await query.answer(
            "Finding 5 different PNGs..."
        )

        await send_png_five(
            context,
            user_id,
            chat_id
        )

        return


# ==========================================
# ERROR HANDLER
# ==========================================

async def error_handler(
    update,
    context
):

    print(
        "BOT ERROR:",
        context.error
    )


# ==========================================
# MAIN
# ==========================================

def main():

    if not BOT_TOKEN:

        print(
            "❌ BOT_TOKEN is missing!"
        )

        return

    if not SERPAPI_KEY:

        print(
            "❌ SERPAPI_KEY is missing!"
        )

        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "🔥 FHD Wallpapers Bot started!"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
