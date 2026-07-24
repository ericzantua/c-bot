"""Canned sample products for local testing without scraping costco.ca.

Loaded via POST /index/mock. Data is representative, not live.
"""
from models import ProductData

SAMPLE_PRODUCTS: list[ProductData] = [
    ProductData(
        item_code="1858512",
        title="Kirkland Signature Down Alternative Comforter",
        brand="Kirkland Signature",
        price="59.99 CAD",
        description="Hypoallergenic down-alternative comforter with a soft "
        "cotton shell. Machine washable and suitable for all seasons.",
        features=[
            "300 thread count cotton shell",
            "Box-stitch construction keeps fill in place",
            "Hypoallergenic microfiber fill",
            "Machine washable",
        ],
        rating="4.7 (2100 reviews)",
        url="https://www.costco.ca/product.1858512.html",
    ),
    ProductData(
        item_code="3118678",
        title="Bionaire True HEPA Air Purifier",
        brand="Bionaire",
        price="129.99 CAD",
        description="True HEPA air purifier for rooms up to 150 sq ft. "
        "Captures 99.97% of airborne particles including dust and pollen.",
        features=[
            "True HEPA filtration",
            "3 fan speeds plus quiet night mode",
            "Covers rooms up to 150 sq ft",
            "Filter-change indicator",
        ],
        rating="4.3 (540 reviews)",
        url="https://www.costco.ca/product.3118678.html",
    ),
    ProductData(
        item_code="1796327",
        title="Lumena FAN STAND 4 Cordless Desk Fan 2 pack, 17.78 cm (7 in.)",
        brand="Lumena",
        price="39.99 CAD",
        description="Cordless 7-inch desk fan, 2-pack (Model FAN STAND 4). "
        "Rechargeable for wireless use, with an auto shut-off timer. "
        "$39.99 after a $10 instant savings off the $49.99 regular price.",
        features=[
            "2 colours (White / Blue)",
            "Wireless use up to 20 hrs",
            "Auto shut-off timer (1 / 2 / 4 / 8 hrs)",
            "17.78 cm (7 in.)",
        ],
        rating="4.9 (17 reviews)",
        url="https://www.costco.ca/product.1796327.html",
    ),
]
