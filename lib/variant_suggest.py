"""Smart variant suggestions for the admin product form.

NOTE (honest): ye koi LLM/AI nahi hai — ek rule-based keyword matcher hai jo
product ke naam + category se andaza lagata hai ke Color / Size / Age me se
kaunse variant options dene chahiye. "AI integration" jaisa mehsoos ho is liye
admin form me auto-suggest popup ki tarah lagta hai, lekin andar simple rules hain.
"""

COLOR_PALETTE = ["Red", "Blue", "Black", "White", "Green", "Yellow",
                 "Pink", "Brown", "Grey", "Navy", "Maroon", "Beige"]

BABY_SIZES = ["0-3 Months", "3-6 Months", "6-12 Months", "1-2 Years"]
APPAREL_SIZES = ["S", "M", "L", "XL", "XXL"]
SHOE_SIZES = ["39", "40", "41", "42", "43", "44"]

_BABY_WORDS = ("baby", "newborn", "infant", "toddler", "kid", "kids",
               "bacha", "bachi", "babies", "suit")
_APPAREL_WORDS = ("shirt", "t-shirt", "tshirt", "kurta", "kurti", "dress",
                  "shalwar", "kameez", "jeans", "trouser", "pajama", "pajamas",
                  "abaya", "hijab", "frock", "coat", "jacket", "sweater",
                  "hoodie", "uniform", "shalwar")
_SHOE_WORDS = ("shoe", "shoes", "sandal", "sandals", "slipper", "slippers",
               "khussa", "sneaker", "sneakers", "boot", "boots", "chappal")
_NON_VARIANT_WORDS = ("watch", "trimmer", "chopper", "grinder", "mixer",
                      "bowl", "bottle", "lamp", "charger", "cable", "machine",
                      "iron", "cooker", "fan", "heater", "electronic", "gadget",
                      "toy", "brush", "comb")


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def suggest_variants(name: str, category: str = "") -> dict:
    """-> {"types": [...], "colors": [...], "sizes": [...], "note": "..."}

    types subset of ["color", "size", "age"]. Empty types = no variants needed.
    """
    text = f"{name or ''} {category or ''}".lower()

    # Baby rule sab se pehle (apparel rule par haavi)
    if _has(text, _BABY_WORDS):
        return {
            "types": ["color", "age"],
            "colors": COLOR_PALETTE,
            "sizes": BABY_SIZES,
            "note": "Baby product lag raha hai — Color + Age suggest kiye hain.",
        }
    if _has(text, _SHOE_WORDS):
        return {
            "types": ["size"],
            "colors": [],
            "sizes": SHOE_SIZES,
            "note": "Footwear lag raha hai — sirf Size (EU) suggest kiya hai.",
        }
    if _has(text, _APPAREL_WORDS):
        return {
            "types": ["color", "size"],
            "colors": COLOR_PALETTE,
            "sizes": APPAREL_SIZES,
            "note": "Kapra lag raha hai — Color + Size suggest kiye hain.",
        }
    if _has(text, _NON_VARIANT_WORDS):
        return {"types": [], "colors": [], "sizes": [],
                "note": "Is product me variants ki zaroorat nahi lag rahi."}
    # default: kuch pata na chale to sirf color ka option do
    return {
        "types": ["color"],
        "colors": COLOR_PALETTE,
        "sizes": [],
        "note": "Sirf Color ka option suggest kiya hai — zaroorat na ho to panel band kar dein.",
    }


def size_dimension_label(types: list) -> str:
    """Storefront pills ke liye label: 'Age' ya 'Size'."""
    return "Age" if "age" in (types or []) else "Size"
