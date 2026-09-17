import csv
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
SETS_DIR = BASE_DIR / "Sets"
FIREBASE_KEY = BASE_DIR / "pokeinv-service.json"


if not firebase_admin._apps:
    cred = credentials.Certificate(str(FIREBASE_KEY))
    firebase_admin.initialize_app(cred)


db = firestore.client()

app = FastAPI(title="PokeInventory")

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


DEBUG_LOG = []


def debug(message):
    message = str(message)

    print(f"[DEBUG] {message}")

    DEBUG_LOG.append(message)

    if len(DEBUG_LOG) > 500:
        DEBUG_LOG.pop(0)


class InventoryItem(BaseModel):
    card_number: str
    condition: str
    variant: str
    quantity: int
    price: float


class InventoryUpdate(BaseModel):
    field: str
    value: str


def normalize(value):
    return " ".join(
        str(value).strip().lower().split()
    )


def load_cards():
    cards = {}

    debug("=== LOADING CARD DATABASE ===")
    debug(f"BASE_DIR: {BASE_DIR}")
    debug(f"SETS_DIR: {SETS_DIR}")
    debug(f"SETS_DIR exists: {SETS_DIR.exists()}")

    if not SETS_DIR.exists():
        debug("ERROR: Sets directory does not exist")
        return cards

    csv_files = sorted(
        SETS_DIR.rglob("*.csv")
    )

    debug(
        f"CSV files found: {len(csv_files)}"
    )

    for csv_file in csv_files:
        relative_path = csv_file.relative_to(
            SETS_DIR
        )

        set_code = csv_file.stem.strip().upper()

        debug(
            f"Loading: {relative_path} | "
            f"set_code={set_code}"
        )

        try:
            with open(
                csv_file,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as file:

                reader = csv.DictReader(file)

                if not reader.fieldnames:
                    debug(
                        f"SKIP {relative_path}: "
                        f"no headers"
                    )
                    continue

                debug(
                    f"Headers for {relative_path}: "
                    f"{reader.fieldnames}"
                )

                field_map = {
                    field.strip().lower(): field
                    for field in reader.fieldnames
                    if field
                }

                number_field = field_map.get(
                    "number"
                )

                name_field = field_map.get(
                    "name"
                )

                rarity_field = field_map.get(
                    "rarity"
                )

                set_field = field_map.get(
                    "set"
                )

                if not number_field:
                    debug(
                        f"SKIP {relative_path}: "
                        f"'Number' column not found"
                    )
                    continue

                card_count = 0

                for row in reader:
                    number = row.get(
                        number_field,
                        ""
                    )

                    if not isinstance(number, str):
                        continue

                    number = number.strip()

                    if not number:
                        continue

                    name = ""

                    if name_field:
                        value = row.get(
                            name_field,
                            ""
                        )

                        if isinstance(value, str):
                            name = value.strip()

                    rarity = ""

                    if rarity_field:
                        value = row.get(
                            rarity_field,
                            ""
                        )

                        if isinstance(value, str):
                            rarity = value.strip()

                    set_name = ""

                    if set_field:
                        value = row.get(
                            set_field,
                            ""
                        )

                        if isinstance(value, str):
                            set_name = value.strip()

                    card = {
                        "number": number,
                        "name": name,
                        "set": set_name,
                        "rarity": rarity,
                        "set_code": set_code,
                    }

                    lookup_key = (
                        f"{set_code} {number}"
                    ).lower()

                    cards[lookup_key] = card

                    card_count += 1

                debug(
                    f"Loaded {card_count} cards "
                    f"from {relative_path}"
                )

        except Exception as error:
            debug(
                f"ERROR loading {relative_path}: "
                f"{type(error).__name__}: {error}"
            )

    debug(
        f"TOTAL cards loaded: {len(cards)}"
    )

    debug("=== CARD DATABASE READY ===")

    return cards


card_database = load_cards()


def find_card_by_code(card_input):
    value = normalize(card_input)

    debug("=" * 60)
    debug(
        f"LOOKUP INPUT: '{value}'"
    )

    parts = value.split()

    if len(parts) != 2:
        debug(
            "INVALID EXACT LOOKUP: "
            "expected SET NUMBER"
        )

        return None

    set_code = parts[0].upper()
    card_number = parts[1]

    lookup_key = (
        f"{set_code} {card_number}"
    ).lower()

    card = card_database.get(
        lookup_key
    )

    if card:
        debug(
            f"CARD FOUND: {card}"
        )
    else:
        debug(
            f"CARD NOT FOUND: "
            f"{lookup_key}"
        )

    debug("=" * 60)

    return card


def search_cards(query, limit=50):
    query = normalize(query)

    if not query:
        return []

    query_parts = query.split()

    results = []

    for card in card_database.values():
        set_code = normalize(
            card.get("set_code", "")
        )

        number = normalize(
            card.get("number", "")
        )

        name = normalize(
            card.get("name", "")
        )

        rarity = normalize(
            card.get("rarity", "")
        )

        set_name = normalize(
            card.get("set", "")
        )

        full_code = (
            f"{set_code} {number}"
        )

        score = 0

        if query == full_code:
            score = 1000

        elif query == number:
            score = 900

        elif query == set_code:
            score = 800

        elif query == name:
            score = 700

        elif name.startswith(query):
            score = 600

        elif full_code.startswith(query):
            score = 550

        elif set_code.startswith(query):
            score = 500

        elif number.startswith(query):
            score = 450

        elif query in name:
            score = 400

        elif query in set_name:
            score = 300

        elif query in rarity:
            score = 200

        else:
            all_parts_match = all(
                part in (
                    full_code,
                    name,
                    set_name,
                    rarity
                )
                or part in name
                or part in full_code
                or part in set_name
                or part in rarity
                for part in query_parts
            )

            if all_parts_match:
                score = 100

        if score > 0:
            results.append(
                (score, card)
            )

    results.sort(
        key=lambda item: (
            -item[0],
            item[1].get(
                "set_code",
                ""
            ),
            item[1].get(
                "number",
                ""
            )
        )
    )

    return [
        card
        for _, card in results[:limit]
    ]


@app.get("/api/debug")
async def get_debug():
    return {
        "success": True,
        "logs": DEBUG_LOG,
        "cards_loaded": len(
            card_database
        ),
        "sets_directory": str(
            SETS_DIR
        ),
    }


@app.get("/api/card")
async def find_card(number: str):
    debug(
        f"API REQUEST /api/card?number={number}"
    )

    card = find_card_by_code(number)

    if not card:
        return {
            "success": False,
            "error": "Card not found",
        }

    return {
        "success": True,
        "card": card,
    }


@app.get("/api/cards/search")
async def search_card_database(
    q: str,
    limit: int = 50
):
    limit = max(
        1,
        min(limit, 100)
    )

    results = search_cards(
        q,
        limit
    )

    return {
        "success": True,
        "query": q,
        "count": len(results),
        "results": results,
    }


@app.get(
    "/",
    response_class=HTMLResponse
)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
    )


@app.get("/api/inventory")
async def get_inventory():
    documents = db.collection(
        "inventory"
    ).stream()

    inventory = []

    for document in documents:
        item = document.to_dict()
        item["id"] = document.id
        inventory.append(item)

    return {
        "success": True,
        "inventory": inventory,
    }


@app.post("/api/inventory")
async def add_inventory(
    item: InventoryItem
):
    card_input = item.card_number.strip()

    card = find_card_by_code(
        card_input
    )

    if not card:
        return {
            "success": False,
            "error": "Card not found in sets database",
        }

    data = {
        "card_number": card.get(
            "number",
            item.card_number
        ),
        "set_code": card.get(
            "set_code",
            ""
        ),
        "name": card.get(
            "name",
            ""
        ),
        "set": card.get(
            "set",
            ""
        ),
        "rarity": card.get(
            "rarity",
            ""
        ),
        "condition": item.condition,
        "variant": item.variant,
        "quantity": max(
            1,
            item.quantity
        ),
        "price": max(
            0,
            item.price
        ),
    }

    document = db.collection(
        "inventory"
    ).add(data)

    return {
        "success": True,
        "id": document[1].id,
        "item": data,
    }


@app.patch(
    "/api/inventory/{item_id}"
)
async def update_inventory(
    item_id: str,
    update: InventoryUpdate
):
    allowed_fields = {
        "card_number",
        "set_code",
        "name",
        "set",
        "rarity",
        "condition",
        "variant",
        "quantity",
        "price",
    }

    if update.field not in allowed_fields:
        return {
            "success": False,
            "error": "Field cannot be edited",
        }

    document_ref = db.collection(
        "inventory"
    ).document(item_id)

    document = document_ref.get()

    if not document.exists:
        return {
            "success": False,
            "error": "Inventory item not found",
        }

    value = update.value

    if update.field == "quantity":
        try:
            value = max(
                0,
                int(value)
            )

        except ValueError:
            return {
                "success": False,
                "error": "Invalid quantity",
            }

    elif update.field == "price":
        try:
            value = max(
                0,
                float(value)
            )

        except ValueError:
            return {
                "success": False,
                "error": "Invalid price",
            }

    document_ref.update({
        update.field: value
    })

    return {
        "success": True,
        "field": update.field,
        "value": value,
    }


@app.delete(
    "/api/inventory/{item_id}"
)
async def delete_inventory(
    item_id: str
):
    db.collection(
        "inventory"
    ).document(item_id).delete()

    return {
        "success": True,
    }