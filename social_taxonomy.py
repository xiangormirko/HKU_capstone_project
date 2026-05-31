"""
Skincare product taxonomy for entity extraction from social posts.

Three relationship types are detected in post/comment text:
  * CATEGORIES   — product categories an e-commerce user would shop by
  * BRANDS       — named skincare brands / product lines
  * INGREDIENTS  — actives / hero ingredients (often shopped as "X serum")

Each entry maps a canonical display name -> list of lowercase surface forms
matched in text. Extend freely; the ingestion picks up new terms automatically.
This is source-agnostic, so future Google Trends / other-platform text reuses it.
"""

CATEGORIES = {
    "Cleanser & Oil Control": [
        "oily skin", "oil control", "oily", "cleanser", "face wash", "facial cleanser",
        "oil cleanser", "double cleanse", "double cleansing", "sebum", "mattify",
        "degrease", "foaming cleanser", "gel cleanser", "micellar", "cleansing balm",
        "oil cleansing", "shine control", "oil free",
    ],
    "Moisturizer & Hydration": [
        "moisturizer", "moisturiser", "moisturizing", "hydrating", "hydration",
        "dry skin", "gel cream", "lotion", "occlusive", "barrier cream", "rich cream",
        "dehydrated", "emollient",
    ],
    "Sunscreen / SPF": [
        "sunscreen", "spf", "sunblock", "uv protection", "suncream", "sun cream",
        "mineral sunscreen", "chemical sunscreen", "reapply",
    ],
    "Exfoliation & Acids": [
        "exfoliant", "exfoliate", "exfoliating", "aha", "bha", "pha", "chemical exfoliant",
        "peeling", "peel", "physical exfoliant", "scrub",
    ],
    "Acne & Blemish": [
        "acne", "pimple", "breakout", "blemish", "spot treatment", "blackhead",
        "whitehead", "fungal acne", "comedone", "cystic", "closed comedones", "milia",
    ],
    "Anti-Aging & Retinoids": [
        "retinol", "retinoid", "anti-aging", "anti aging", "antiaging", "wrinkle",
        "fine lines", "firming", "collagen", "mature skin", "sagging",
    ],
    "Brightening & Dark Spots": [
        "brightening", "dark spot", "dark spots", "hyperpigmentation", "melasma",
        "even tone", "even skin tone", "pigmentation", "scarring", "acne scars",
        "post-inflammatory", "pih", "brighten",
    ],
    "Serums & Essences": [
        "serum", "essence", "ampoule", "treatment essence", "facial serum",
    ],
    "Toners": ["toner", "toning", "astringent", "hydrating toner"],
    "Masks": [
        "face mask", "sheet mask", "clay mask", "overnight mask", "sleeping mask",
        "sleeping pack", "wash off mask",
    ],
    "Eye Care": ["eye cream", "dark circles", "under eye", "under-eye", "puffiness", "eye serum"],
    "Sensitive & Barrier": [
        "sensitive skin", "redness", "rosacea", "irritation", "barrier repair",
        "fragrance free", "fragrance-free", "compromised barrier", "skin barrier",
        "eczema", "flaky",
    ],
    "Lip Care": ["lip balm", "chapstick", "lip mask", "chapped lips", "lip care"],
    "Pores & Texture": ["pores", "large pores", "texture", "rough texture", "smooth skin", "bumpy"],
}

BRANDS = {
    "CeraVe": ["cerave"],
    "Cetaphil": ["cetaphil"],
    "La Roche-Posay": ["la roche-posay", "la roche posay", "laroche-posay", "lrp"],
    "The Ordinary": ["the ordinary"],
    "Paula's Choice": ["paula's choice", "paulas choice", "paula’s choice"],
    "Neutrogena": ["neutrogena"],
    "COSRX": ["cosrx"],
    "Anua": ["anua"],
    "Beauty of Joseon": ["beauty of joseon", "boj"],
    "Skin1004": ["skin1004"],
    "Isntree": ["isntree"],
    "Round Lab": ["round lab", "roundlab"],
    "Purito": ["purito"],
    "Some By Mi": ["some by mi", "somebymi"],
    "Innisfree": ["innisfree"],
    "Laneige": ["laneige"],
    "Glow Recipe": ["glow recipe"],
    "Drunk Elephant": ["drunk elephant"],
    "Eucerin": ["eucerin"],
    "Vanicream": ["vanicream"],
    "Differin": ["differin"],
    "La Mer": ["la mer"],
    "Tatcha": ["tatcha"],
    "Kiehl's": ["kiehl's", "kiehls"],
    "First Aid Beauty": ["first aid beauty"],
    "Good Molecules": ["good molecules"],
    "Naturium": ["naturium"],
    "Versed": ["versed"],
    "Hada Labo": ["hada labo", "hadalabo"],
    "Bioderma": ["bioderma"],
    "Avene": ["avene", "avène"],
    "Vichy": ["vichy"],
    "Aveeno": ["aveeno"],
    "Olay": ["olay"],
    "Garnier": ["garnier"],
    "Clinique": ["clinique"],
    "Medik8": ["medik8"],
    "SkinCeuticals": ["skinceuticals"],
    "Krave Beauty": ["krave beauty", "krave"],
    "Stratia": ["stratia"],
    "Skinfix": ["skinfix"],
    "Byoma": ["byoma"],
    "Mixsoon": ["mixsoon"],
    "Torriden": ["torriden"],
    "Numbuzin": ["numbuzin", "numbuzzin"],
}

INGREDIENTS = {
    "Niacinamide": ["niacinamide"],
    "Hyaluronic Acid": ["hyaluronic acid", "hyaluronic", "ha serum"],
    "Salicylic Acid (BHA)": ["salicylic acid", "salicylic"],
    "Glycolic Acid": ["glycolic acid", "glycolic"],
    "Lactic Acid": ["lactic acid"],
    "Azelaic Acid": ["azelaic acid", "azelaic"],
    "Mandelic Acid": ["mandelic acid", "mandelic"],
    "Retinol / Retinoid": ["retinol", "retinoid", "retinaldehyde", "retinic"],
    "Tretinoin": ["tretinoin", "tret", "retin-a", "retin a"],
    "Adapalene": ["adapalene"],
    "Benzoyl Peroxide": ["benzoyl peroxide", "bpo"],
    "Vitamin C": ["vitamin c", "ascorbic acid", "l-ascorbic", "vit c"],
    "Ceramides": ["ceramide", "ceramides"],
    "Panthenol": ["panthenol", "b5"],
    "Centella / Cica": ["centella", "cica", "madecassoside"],
    "Snail Mucin": ["snail mucin", "snail"],
    "Peptides": ["peptide", "peptides"],
    "Zinc": ["zinc oxide", "zinc pca"],
    "Tranexamic Acid": ["tranexamic acid", "tranexamic"],
    "Squalane": ["squalane"],
    "Allantoin": ["allantoin"],
    "Arbutin": ["arbutin", "alpha arbutin"],
    "Urea": ["urea"],
    "Propolis": ["propolis"],
    "PDRN": ["pdrn", "polynucleotide"],
}

# Convenience: type label -> canonical->synonyms dict
TAXONOMY = {
    "category": CATEGORIES,
    "brand": BRANDS,
    "ingredient": INGREDIENTS,
}
