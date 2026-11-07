import base64
import json
import mimetypes
import os
import time
from urllib.parse import urlparse

import requests

# Yuvomi / Körbchen configuration
YUVOMI_API_BASE_URL = '<Yuvomi-URL>'
INGESTION_AUTH_TOKEN = '<TOKEN>'
KOERBCHEN_RECIPES_PATH = os.getenv('KOERBCHEN_RECIPES_PATH', 'koerbchen_recipes.json')
TARGET_ENDPOINT = '/api/v1/recipes'

# The API stores recipe pictures as data URLs. If your installed Yuvomi build
# uses another property name, override it without editing the script:
#   Windows PowerShell: $env:YUVOMI_IMAGE_FIELD='image'
#   Linux/macOS:       export YUVOMI_IMAGE_FIELD=image
YUVOMI_IMAGE_FIELD = os.getenv('YUVOMI_IMAGE_FIELD', 'image')
# The source URL is preserved in the recipe payload under this field.
# Override if your Yuvomi build expects a different field name.
YUVOMI_SOURCE_FIELD = "recipe_url"

SESSION = requests.Session()
SESSION.headers.update({
    'Authorization': f'Bearer {INGESTION_AUTH_TOKEN}',
    'Accept': 'application/json',
    'User-Agent': 'Koerbchen-Yuvomi-Importer/1.1',
})


def load_recipes(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError('Die JSON-Datei muss eine Liste von Rezepten enthalten.')
    return data


def download_image_as_data_url(image_info):
    """Download the actual Körbchen image and encode it as a data URL.

    Körbchen's image id (often 'default') is NOT a Yuvomi image id. The image
    URL is the transferable asset. Placeholder images are deliberately skipped.
    """
    if not isinstance(image_info, dict):
        return None
    image_url = image_info.get('url')
    image_id = str(image_info.get('id') or '').lower()
    if not image_url or image_id == 'default' or 'placeholder_recipe' in image_url:
        return None
    parsed = urlparse(image_url)
    if parsed.scheme not in ('http', 'https'):
        print(f"Bild übersprungen: ungültiges URL-Schema ({parsed.scheme})")
        return None
    try:
        response = requests.get(image_url, timeout=30, stream=True)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
        image_bytes = response.content
        if not content_type.startswith('image/'):
            content_type = mimetypes.guess_type(parsed.path)[0] or 'image/jpeg'
        if len(image_bytes) > 5 * 1024 * 1024:
            print('   Bild übersprungen: größer als 5 MB (Yuvomi-Uploadgrenze laut Version).')
            return None
        encoded = base64.b64encode(image_bytes).decode('ascii')
        return f'data:{content_type};base64,{encoded}'
    except requests.RequestException as exc:
        print(f'   Bild konnte nicht geladen werden: {exc}')
        return None


def transform_to_yuvomi_recipe(recipe):
    ingredients_list = []
    instructions_list = []

    for instruction in recipe.get('instructions') or []:
        if isinstance(instruction, dict):
            text = instruction.get('text')
            title = instruction.get('title')
            if text:
                instructions_list.append(f"{title}: {text}" if title else text)
        elif isinstance(instruction, str) and instruction.strip():
            instructions_list.append(instruction.strip())

    # Important: process EVERY ingredient list, not just [0].
    for ingredient_group in recipe.get('ingredientLists') or []:
        if not isinstance(ingredient_group, dict):
            continue
        for entry in ingredient_group.get('ingredients') or []:
            if not isinstance(entry, dict):
                continue
            product = entry.get('product') or {}
            unit = entry.get('unit') or {}
            amount = entry.get('amount')
            unit_name = unit.get('name') if isinstance(unit, dict) else str(unit or '')
            quantity = ''
            if amount not in (None, 0, 0.0, ''):
                quantity = str(amount)
            if unit_name:
                quantity = f'{quantity} {unit_name}'.strip()
            mapped = {'name': product.get('name') or entry.get('name') or ''}
            if quantity:
                mapped['quantity'] = quantity
            if product.get('group', {}).get('id'):
                mapped['product_id'] = product['group']['id']
            ingredients_list.append(mapped)

    payload = {
        'title': recipe.get('title') or 'Ohne Titel',
        'notes': '\n\n'.join(instructions_list),
        'ingredients': ingredients_list,
    }

    # FIX 1: Körbchen JSON uses 'source', NOT 'recipe_url'. Preserve the full URL.
    source_url = recipe.get('source')
    if isinstance(source_url, str) and source_url.strip():
        payload[YUVOMI_SOURCE_FIELD] = source_url.strip()

    # FIX 2: transfer the actual image bytes, not Körbchen's unrelated image id.
    images = recipe.get('images') or []
    if images:
        image_data_url = download_image_as_data_url(images[0])
        if image_data_url:
            payload[YUVOMI_IMAGE_FIELD] = image_data_url

    return payload


def send_to_yuvomi(payload, dry_run=False):
    if not INGESTION_AUTH_TOKEN:
        raise RuntimeError('Bitte YUVOMI_TOKEN als Umgebungsvariable setzen; Token nicht im Skript speichern.')
    url = YUVOMI_API_BASE_URL + TARGET_ENDPOINT
    if dry_run:
        print(f"Vorschau: {payload.get('title')} | Quelle: {bool(payload.get(YUVOMI_SOURCE_FIELD))} | Bild: {bool(payload.get(YUVOMI_IMAGE_FIELD))}")
        return True
    for attempt in range(3):
        try:
            response = SESSION.post(url, json=payload, timeout=45)
            if response.status_code in (200, 201):
                print(f"OK: {payload.get('title')} (HTTP {response.status_code})")
                print("API-Antwort:", response.text[:3000])
                return True
            print(f"FEHLER {payload.get('title')}: HTTP {response.status_code}: {response.text[:1500]}")
            return False
        except requests.RequestException as exc:
            print(f'Verbindungsfehler (Versuch {attempt + 1}/3): {exc}')
            if attempt < 2:
                time.sleep(5)
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Körbchen → Yuvomi Rezeptimport')
    parser.add_argument('--limit', type=int, default=1000, help='Anzahl Rezepte (Standard: 3)')
    parser.add_argument('--apply', action='store_true', help='Tatsächlich importieren; ohne diese Option nur Vorschau')
    args = parser.parse_args()

    recipes = load_recipes(KOERBCHEN_RECIPES_PATH)
    print(f'{len(recipes)} Rezepte geladen. Ziel: {YUVOMI_API_BASE_URL}')
    batch = recipes[:max(args.limit, 0)]
    ok = 0
    for recipe in batch:
        payload = transform_to_yuvomi_recipe(recipe)
        ok += bool(send_to_yuvomi(payload, dry_run=not args.apply))
    print(f'Abgeschlossen: {ok}/{len(batch)} verarbeitet. ' + ('Import ausgeführt.' if args.apply else 'Nur Vorschau – nichts geschrieben.'))


if __name__ == '__main__':
    main()
