import os
import requests
import base64
import uuid
from dotenv import load_dotenv

load_dotenv()

# Configuration - set GROCY_BASE_URL and GROCY_API_KEY to your Grocy instance details
GROCY_BASE_URL = os.getenv('GROCY_BASE_URL', 'http://grocy.example.com')
GROCY_API_URL = f"{GROCY_BASE_URL}/api/objects/equipment"
EQUIPMENT_MANUALS_API_URL = f"{GROCY_BASE_URL}/api/files/equipmentmanuals"
USERFILE_API_URL = f"{GROCY_BASE_URL}/files/userfiles"
API_KEY = os.getenv('GROCY_API_KEY')
OUTPUT_DIR = "equipment_output"  # Directory where folders will be saved
UUID_LENGTH = 8

# Headers for the API request
headers = {
    "GROCY-API-KEY": API_KEY
}
# Function to create a folder and save equipment details in index.md
def create_equipment_folder(equipment, location, output_dir):
    # Create a folder for the location if it doesn't exist
    location_folder = os.path.join(output_dir, location)
    os.makedirs(location_folder, exist_ok=True)

    # Create a folder for each equipment within the location folder
    equipment_folder = os.path.join(location_folder, equipment['name'])
    os.makedirs(equipment_folder, exist_ok=True)

    # Create an index.md file with the equipment description
    md_file_path = os.path.join(equipment_folder, "index.md")
    with open(md_file_path, "w") as md_file:
        md_file.write(f"---\n")
        random_id = uuid.uuid4().bytes
        base64_id = base64.urlsafe_b64encode(
            random_id).decode('utf-8')[:UUID_LENGTH]
        md_file.write(f"id: {base64_id}\n")
        md_file.write(f"---\n")
        md_file.write(f"{equipment.get('description', '')}\n")

     # Download the manual if it exists
    download_manual(equipment.get('instruction_manual_file_name'), equipment_folder)


# Function to download the equipment manual
def download_manual(manual_id, equipment_folder):
    if not manual_id:
        return

    manual_url = f"{EQUIPMENT_MANUALS_API_URL}/{base64.b64encode(manual_id.encode('utf-8')).decode('ascii')}"
    manual_file_path = os.path.join(equipment_folder, 'manual'+str(os.path.splitext(manual_id)[-1]))
    print(f"Downloading manual {manual_id} to {manual_file_path}")
    response = requests.get(manual_url, headers=headers)
    

    # Download the manual file
    if response.status_code == 200:
        with open(manual_file_path, "wb") as manual_file:
            manual_file.write(response.content)
    else:
        print(f"Failed to fetch manual for equipment ID {manual_id}")

def download_additional_file(file_id, equipment_folder):
    if not file_id:
        return

    manual_url = f"{EQUIPMENT_MANUALS_API_URL}/{file_id}"
    manual_file_path = os.path.join(equipment_folder, file_id)
    print(f"Downloading manual {manual_id} to {manual_file_path}")
    response = requests.get(manual_url, headers=headers)
    

    # Download the manual file
    if response.status_code == 200:
        with open(manual_file_path, "wb") as manual_file:
            manual_file.write(response.content)
    else:
        print(f"Failed to fetch manual for equipment ID {manual_id}")
# Fetch the equipment data from the Grocy API
def fetch_equipment():
    response = requests.get(GROCY_API_URL, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fetch equipment data: {response.status_code}")
        return []

# Function to get the location for an equipment item
def get_equipment_location(equipment, OUTPUT_DIR):
    # Assuming each equipment item has a location ID or name stored
    # This function might need to query a separate API or data field to get location info
    location =equipment['userfields']['Location']
    location_description =equipment['userfields']['locdescription']
    location_path = 'Unknown'
    if location:
        location_path = location
        if location_description:
            create_equipment_folder({'name':location_description}, location_path, OUTPUT_DIR)
            location_path = location_path + '/' + location_description
    return location_path

# Main function to process the equipment
def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # Fetch all equipment
    equipment_list = fetch_equipment()
    if not equipment_list:
        print("No equipment data found.")
        return

    # Process each equipment item and group by location
    for equipment in equipment_list:
        location = get_equipment_location(equipment, OUTPUT_DIR)
        create_equipment_folder(equipment, location, OUTPUT_DIR)

if __name__ == "__main__":
    main()
