import csv
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from pylibdmtx import pylibdmtx

# Helper function to generate a Data Matrix barcode from a code value
def generate_datamatrix_barcode(code_value):
    # Create the barcode using pylibdmtx
    barcode = pylibdmtx.encode(code_value.encode('utf8'))
    barcode_image = Image.frombytes('RGB', (barcode.width, barcode.height), barcode.pixels)
    return barcode_image

# Function to read CSV and get the data
def read_csv(csv_file):
    codes = []
    labels = []
    with open(csv_file, mode='r') as file:
        reader = csv.reader(file)
        rows = list(reader)
        print(rows)
        for i in range(len(rows)):
            codes.append(rows[i][0])  # First row: barcode values (code values)
            labels.append(rows[i][1])  # Second row: labels for barcodes
    return codes, labels

# Function to create the image with barcodes
def create_barcode_image(codes, labels, output_image_file):
    # Image dimensions (8.5"x11", 300 dpi = 2550x3300 pixels)
    image_width = 2550
    image_height = 3300
    background_color = (255, 255, 255)
    barcode_width = 300
    barcode_height = 300
    padding = 100  # Padding between barcodes
    font_size = 40

    # Create a new blank image (white background)
    image = Image.new("RGB", (image_width, image_height), background_color)
    draw = ImageDraw.Draw(image)

    # Set up font (use default font or specify path to a font file)
    try:
        font_path = str(Path(__file__).parent.parent / "src" / "roboto.ttf")
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        font = ImageFont.load_default()

    x_offset = padding
    y_offset = padding
    print(codes)

    # Generate and arrange barcodes in 3 columns
    for i in range(len(codes)):
        # Generate Data Matrix barcode
        barcode_image = generate_datamatrix_barcode(codes[i])

        # Resize barcode image to fit within the layout
        barcode_image = barcode_image.resize((barcode_width, barcode_height))

        # Paste the barcode onto the main image
        image.paste(barcode_image, (x_offset, y_offset))

        # Draw the label below the barcode
        text_bbox = draw.textbbox((0, 0), labels[i], font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        label_x = x_offset + (barcode_width - text_width) // 2
        label_y = y_offset + barcode_height + padding//2
        draw.text((label_x, label_y), labels[i], font=font, fill=(0, 0, 0))

        # Update offsets for next barcode (3 columns layout)
        x_offset += barcode_width + padding
        if (i + 1) % 4 == 0:  # Move to the next row after every 3rd barcode
            x_offset = padding
            y_offset += barcode_height + text_height + padding * 2

    # Save the generated image to a file
    image.save(output_image_file)

# Example usage
csv_file = 'barcodes.csv'  # Your input CSV file
output_image_file = 'barcode_output.png'  # Output image file

codes, labels = read_csv(csv_file)
create_barcode_image(codes, labels, output_image_file)

print("Barcode image generated successfully.")
