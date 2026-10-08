from selenium import webdriver
import time

print("Starting Chrome...")

driver = webdriver.Chrome()

print("Opening Google...")

driver.get("https://www.google.com")

print("Page title:", driver.title)

time.sleep(5)

driver.quit()

print("Test completed successfully!")