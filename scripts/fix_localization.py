"""One-time script to update EN and ES localization with emoji and new keys."""
import pathlib, re

FILE = pathlib.Path(__file__).resolve().parent.parent / "bot" / "localization" / "messages.py"

content = FILE.read_text(encoding="utf-8")

# ── NEW EN BLOCK ──────────────────────────────────────────────────────────
new_en = '''    "en": {
        "start": "👋 Hi there! I turn your ideas into stunning images ✨\\nJust describe what you want — and I'll make it real!",
        "menu.generate": "🎨 Generate",
        "menu.subscription": "💎 Subscription",
        "menu.help": "🆘 Help",
        "menu.language": "🌐 Language",
        "generate.stub": "🖌️ Tap <b>Create</b> to describe your idea and get a unique artwork!",
        "generate.menu.title": "🎛️ <b>Image Studio</b>\\nChoose what you'd like to do:",
        "generate.menu.create": "🖼️ Create",
        "generate.menu.edit": "✏️ Edit",
        "generate.menu.mix": "🌀 Blend",
        "generate.menu.back": "⬅️ Main menu",
        "generate.prompt.ask": "💬 Describe the image you want me to create.\\nBe detailed — the more info, the better the result!",
        "generate.prompt.empty": "⚠️ Please send a text description first.",
        "generate.ratio.ask": "📐 Choose the aspect ratio for your image:",
        "generate.variants.ask": "🔢 How many variations would you like?",
        "generate.processing": "🖌️ Painting image <b>{current}</b>/<b>{total}</b>…",
        "generate.processing.submitted": "⏳ Task submitted, starting generation…",
        "generate.progress.queued": "🕐 In queue, hang tight…",
        "generate.progress.in_progress": "🎨 Creating your masterpiece…",
        "generate.progress.generating": "🎨 Painting away…",
        "generate.progress.completed": "✅ Done!",
        "generate.ready": "🎉 All done! Sending your artworks…",
        "generate.caption": "🖼️ Variant <b>{current}</b>/<b>{total}</b> ({ratio})",
        "generate.error": "😔 Couldn't generate the image. Please try again later.",
        "generate.error.rate_limit": "⚡ Server is busy — please wait a moment and try again.",
        "generate.actions.title": "✨ What's next?",
        "generate.actions.regenerate": "♻️ Regenerate",
        "generate.actions.edit": "✏️ Edit",
        "generate.actions.new": "✨ New image",
        "generate.actions.unavailable": "🖼️ Generate an image first to unlock these options.",
        "generate.regen.prompt": "🔄 Regenerate the last prompt? Pick how many new variations.",
        "generate.edit.choose_image": "🖼️ Which image do you want to edit?",
        "generate.edit.selected": "✅ Image <b>#{number}</b> selected.",
        "generate.edit.prompt.ask": "✏️ Describe the changes you'd like to make.",
        "generate.edit.prompt.example": "💡 E.g. \\u201cmake the background darker and add neon lights\\u201d",
        "generate.edit.prompt.empty": "⚠️ Please describe what to edit.",
        "generate.edit.stub": "🔜 Editing mode is coming soon!",
        "generate.mix.stub": "🔜 Blend mode is under construction.",
        "subscription.stub": "💳 Subscription plans are coming soon!",
        "help.stub": "ℹ️ Type /help or contact the admin team.",
        "language.prompt": "🌐 Choose your language:",
        "language.updated": "✅ Language switched to <b>{language}</b>!",
    },'''

# ── NEW ES BLOCK ──────────────────────────────────────────────────────────
new_es = '''    "es": {
        "start": "👋 ¡Hola! Convierto tus ideas en imágenes increíbles ✨\\n¡Solo describe lo que quieres y lo haré realidad!",
        "menu.generate": "🎨 Generar",
        "menu.subscription": "💎 Suscripción",
        "menu.help": "🆘 Ayuda",
        "menu.language": "🌐 Idioma",
        "generate.stub": "🖌️ Pulsa <b>Crear</b> para describir tu idea y obtener una obra única.",
        "generate.menu.title": "🎛️ <b>Estudio de imágenes</b>\\nElige qué quieres hacer:",
        "generate.menu.create": "🖼️ Crear",
        "generate.menu.edit": "✏️ Editar",
        "generate.menu.mix": "🌀 Combinar",
        "generate.menu.back": "⬅️ Menú principal",
        "generate.prompt.ask": "💬 Describe la imagen que quieres crear.\\nSé detallado — cuantos más detalles, mejor el resultado.",
        "generate.prompt.empty": "⚠️ Envía primero una descripción en texto.",
        "generate.ratio.ask": "📐 Elige la relación de aspecto:",
        "generate.variants.ask": "🔢 ¿Cuántas variantes quieres?",
        "generate.processing": "🖌️ Creando imagen <b>{current}</b>/<b>{total}</b>…",
        "generate.processing.submitted": "⏳ Tarea enviada, comenzando la generación…",
        "generate.progress.queued": "🕐 En cola, espera un momento…",
        "generate.progress.in_progress": "🎨 Creando tu obra maestra…",
        "generate.progress.generating": "🎨 Pintando…",
        "generate.progress.completed": "✅ ¡Listo!",
        "generate.ready": "🎉 ¡Todo listo! Enviando tus obras…",
        "generate.caption": "🖼️ Variante <b>{current}</b>/<b>{total}</b> ({ratio})",
        "generate.error": "😔 No se pudo generar la imagen. Inténtalo más tarde.",
        "generate.error.rate_limit": "⚡ El servidor está ocupado — espera un momento e inténtalo de nuevo.",
        "generate.actions.title": "✨ ¿Qué hacemos ahora?",
        "generate.actions.regenerate": "♻️ Regenerar",
        "generate.actions.edit": "✏️ Editar",
        "generate.actions.new": "✨ Nueva imagen",
        "generate.actions.unavailable": "🖼️ Primero crea una imagen para activar estas opciones.",
        "generate.regen.prompt": "🔄 ¿Regeneramos el último prompt? Elige cuántas variantes.",
        "generate.edit.choose_image": "🖼️ ¿Qué imagen editamos?",
        "generate.edit.selected": "✅ Imagen <b>#{number}</b> seleccionada.",
        "generate.edit.prompt.ask": "✏️ Describe qué cambios quieres hacer.",
        "generate.edit.prompt.example": "💡 Ej.: \\u201coscurece el fondo y agrega luces neón\\u201d",
        "generate.edit.prompt.empty": "⚠️ Describe qué editar, por favor.",
        "generate.edit.stub": "🔜 El modo de edición estará disponible pronto.",
        "generate.mix.stub": "🔜 La mezcla de imágenes aún está en desarrollo.",
        "subscription.stub": "💳 Las suscripciones estarán disponibles pronto.",
        "help.stub": "ℹ️ Escribe /help o contacta con un administrador.",
        "language.prompt": "🌐 Elige tu idioma:",
        "language.updated": "✅ Idioma cambiado a <b>{language}</b>!",
    },'''

# Find and replace EN block: from '    "en": {' to next '    },'
en_pattern = re.compile(r'    "en": \{.*?\n    \},', re.DOTALL)
es_pattern = re.compile(r'    "es": \{.*?\n    \},', re.DOTALL)

en_match = en_pattern.search(content)
es_match = es_pattern.search(content)

if not en_match:
    print("ERROR: could not find EN block")
else:
    print(f"EN block found at {en_match.start()}..{en_match.end()}")
    content = content[:en_match.start()] + new_en + content[en_match.end():]

# Re-search ES after replacement (offsets shifted)
es_match = es_pattern.search(content)
if not es_match:
    print("ERROR: could not find ES block")
else:
    print(f"ES block found at {es_match.start()}..{es_match.end()}")
    content = content[:es_match.start()] + new_es + content[es_match.end():]

FILE.write_text(content, encoding="utf-8")
print("Done! File updated successfully.")
