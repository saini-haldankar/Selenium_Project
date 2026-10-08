import csv
import re
import time
from datetime import date
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# CONFIGURATION
# ============================================================

LOCATION = "Goa, India"

CHECK_IN = date(2026, 9, 10)
CHECK_OUT = date(2026, 9, 11)

DATE_RANGE = (
    f"{CHECK_IN.strftime('%d-%m-%Y')} "
    f"to "
    f"{CHECK_OUT.strftime('%d-%m-%Y')}"
)

OUTPUT_FILE = "oyo_goa_hotels.csv"
WAIT_TIME = 30
BASE_URL = "https://www.oyorooms.com/hotels-in-goa/"


# ============================================================
# START CHROME (UBUNTU COMPATIBLE)
# ============================================================

print("=" * 70)
print("OYO AUTOMATED QA WEB TEST")
print("=" * 70)

options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, WAIT_TIME)


# ============================================================
# HELPERS
# ============================================================

def is_visible(element):
    try:
        return element.is_displayed()
    except Exception:
        return False


def safe_text(element):
    try:
        return element.text.strip()
    except Exception:
        return ""


def create_goa_search_url():
    parsed = urlparse(BASE_URL)
    query = parse_qs(parsed.query, keep_blank_values=True)

    query["city"] = ["Goa"]
    query["country"] = ["India"]
    query["checkin"] = [CHECK_IN.strftime("%Y-%m-%d")]
    query["checkout"] = [CHECK_OUT.strftime("%Y-%m-%d")]
    query["start_date"] = [CHECK_IN.strftime("%Y-%m-%d")]
    query["end_date"] = [CHECK_OUT.strftime("%Y-%m-%d")]

    new_query = urlencode(query, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


def scroll_to_load_all_hotels(driver, max_scrolls=15):
    """Scrolls down incrementally to force dynamic loading of all hotel cards."""
    print("\nScrolling page to load all dynamic hotel cards...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    
    for i in range(max_scrolls):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            print(f"Reached end of page after {i + 1} scrolls.")
            break
        last_height = new_height

    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)


# ============================================================
# OPEN OYO AND NAVIGATE
# ============================================================

print("\nOpening OYO Rooms...")
driver.get("https://www.oyorooms.com/")
wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

goa_url = create_goa_search_url()
print("\nOpening Goa hotel listing URL:", goa_url)
driver.get(goa_url)

wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
time.sleep(5)

body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
if "goa" not in body_text:
    raise RuntimeError("Goa listing page was not loaded.")

print("Goa listing confirmed.")

# Scroll to reveal all dynamically loaded listings
scroll_to_load_all_hotels(driver)


# ============================================================
# FIND HOTEL LINKS
# ============================================================

def get_hotel_links():
    links = driver.find_elements(By.XPATH, "//a[@href]")
    hotels = []
    seen_urls = set()

    for link in links:
        try:
            href = link.get_attribute("href")
            name = link.text.strip()

            if not href or not name:
                continue

            parsed = urlparse(href)
            if parsed.netloc not in ("www.oyorooms.com", "oyorooms.com"):
                continue

            path = parsed.path.rstrip("/")

            excluded = (
                path == ""
                or path == "/allcities"
                or path.startswith("/hotels-in-")
                or path.startswith("/flagship-hotels")
                or path.startswith("/collections")
                or path.startswith("/login")
                or path.startswith("/signup")
                or path.startswith("/about")
                or path.startswith("/contact")
            )

            if excluded or not re.search(r"/\d+$", path):
                continue

            if href in seen_urls:
                continue

            name = name.split("\n")[0].strip()
            if len(name) < 3:
                continue

            seen_urls.add(href)
            hotels.append({
                "hotel_name": name,
                "url": href,
                "element": link
            })
        except Exception:
            continue

    return hotels


hotels = get_hotel_links()

# Deduplicate hotels
unique_hotels = []
seen_names = set()
seen_urls = set()

for hotel in hotels:
    name_key = hotel["hotel_name"].lower()
    url = hotel["url"]

    if name_key in seen_names or url in seen_urls:
        continue

    seen_names.add(name_key)
    seen_urls.add(url)
    unique_hotels.append(hotel)

hotels = unique_hotels
print(f"Total unique hotel links found: {len(hotels)}")


# ============================================================
# AVAILABILITY LOGIC
# ============================================================

def get_listing_availability(hotel):
    """
    Limits ancestor traversal to maximum 5 parent levels to keep scope
    within individual hotel cards and prevent leaks to page-wide elements.
    """
    try:
        element = hotel["element"]
        for _ in range(5):
            element = element.find_element(By.XPATH, "..")
            text = safe_text(element).lower()

            if "sold out" in text:
                return False
            if "book now" in text or "view details" in text:
                return True
    except Exception:
        pass

    return None


def get_hotel_page_availability(hotel):
    original_window = driver.current_window_handle

    try:
        driver.execute_script("window.open(arguments[0], '_blank');", hotel["url"])
        wait.until(EC.number_of_windows_to_be(2))

        new_window = [h for h in driver.window_handles if h != original_window][0]
        driver.switch_to.window(new_window)

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3)

        elements = driver.find_elements(By.XPATH, "//*[self::button or self::a or @role='button']")

        for element in elements:
            try:
                text = safe_text(element).lower()
                if "continue to book" in text:
                    return True
                if "sold out" in text:
                    return False
            except Exception:
                continue

        body = driver.find_element(By.TAG_NAME, "body").text.lower()
        if "continue to book" in body:
            return True
        if "sold out" in body:
            return False

        return None

    except Exception as error:
        print("Hotel page error:", error)
        return None

    finally:
        try:
            if driver.current_window_handle != original_window:
                driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(original_window)
        except Exception:
            pass


# ============================================================
# INITIALIZE CSV
# ============================================================

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as csv_file:
    writer = csv.DictWriter(
        csv_file,
        fieldnames=[
            "hotel_name",
            "date_range",
            "isAvailableOnListing",
            "isAvailableOnHotelPage",
        ],
    )
    writer.writeheader()


# ============================================================
# PROCESS HOTELS
# ============================================================

print("\n" + "=" * 70)
print("PROCESSING GOA HOTELS")
print("=" * 70)

for index, hotel in enumerate(hotels, start=1):
    print(f"\n[{index}/{len(hotels)}] Hotel: {hotel['hotel_name']}")

    listing_status = get_listing_availability(hotel)
    print("Listing Availability:", "Book Now" if listing_status is True else "Sold Out" if listing_status is False else "NOT FOUND")

    hotel_page_status = get_hotel_page_availability(hotel)
    print("Hotel Page Availability:", "Continue to Book" if hotel_page_status is True else "Sold Out" if hotel_page_status is False else "NOT FOUND")

    row = {
        "hotel_name": hotel["hotel_name"],
        "date_range": DATE_RANGE,
        "isAvailableOnListing": listing_status,
        "isAvailableOnHotelPage": hotel_page_status,
    }

    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "hotel_name",
                "date_range",
                "isAvailableOnListing",
                "isAvailableOnHotelPage",
            ],
        )
        writer.writerow(row)


# ============================================================
# FINISH
# ============================================================

print("\n" + "=" * 70)
print("TEST COMPLETED")
print("=" * 70)
print("Date Range:", DATE_RANGE)
print("Hotels Processed:", len(hotels))
print("Output File:", OUTPUT_FILE)

driver.quit()
print("\nDriver closed successfully.")