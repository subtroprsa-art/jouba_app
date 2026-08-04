import os
import logging
from typing import List, Dict, Any, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_floor_record_file(file_path: str) -> Tuple[int, int]:
    """
    Processes an individual floor record file and returns (items_processed, bag_total).
    
    Note: As per business rules, 15kg and 20kg items are included in bag_total.
    """
    items_processed = 0
    bag_total = 0

    try:
        # Placeholder processing logic for floor record files
        # Replace this block with your specific file parsing (e.g., CSV, JSON, Excel)
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                items_processed += 1
                
                # Example rule: Count 15kg and 20kg records as part of the bag total
                if "15kg" in line or "20kg" in line or "bag" in line.lower():
                    bag_total += 1

    except Exception as e:
        logger.error(f"Error processing file {file_path}: {e}")
        
    # Return as a tuple of counts
    return (items_processed, bag_total)


def process_drive_folder(folder_path: str) -> Dict[str, Any]:
    """
    Recursively scans and processes floor records inside a Google Drive sync folder.
    
    Fixes the TypeError by properly unpacking tuples returned by sub-functions
    and maintaining separate integer accumulators for numeric totals.
    """
    if not os.path.exists(folder_path):
        logger.error(f"Folder path does not exist: {folder_path}")
        return {
            "status": "error",
            "message": f"Path not found: {folder_path}",
            "processed_files": 0,
            "total_items": 0,
            "total_bags": 0,
            "records": ()
        }

    # Integer counters (preventing tuple-int addition bugs)
    processed_files_count = 0
    total_items = 0
    total_bags = 0
    
    # Tuple to store individual record metadata/results
    floor_records: Tuple[Dict[str, Any], ...] = ()

    for root, _, files in os.walk(folder_path):
        for file_name in files:
            # Process floor record files (e.g., CSV, JSON, TXT)
            if file_name.endswith(('.csv', '.json', '.txt', '.dat')):
                file_path = os.path.join(root, file_name)
                
                # Unpack returned tuple explicitly into integer variables
                file_items, file_bags = process_floor_record_file(file_path)
                
                processed_files_count += 1
                total_items += file_items
                total_bags += file_bags
                
                record_info = {
                    "file_name": file_name,
                    "items": file_items,
                    "bags": file_bags
                }
                
                # FIX 1: Proper tuple concatenation requires a trailing comma: (record_info,)
                floor_records = floor_records + (record_info,)

    summary = {
        "status": "success",
        "folder": folder_path,
        "processed_files": processed_files_count,
        "total_items": total_items,
        "total_bags": total_bags,
        "floor_records": floor_records
    }

    logger.info(f"Processed {processed_files_count} files in {folder_path}.")
    return summary


if __name__ == "__main__":
    # Test execution
    target_folder = "./floor_records"
    if not os.path.exists(target_folder):
        os.makedirs(target_folder, exist_ok=True)
        # Create a dummy test file
        with open(os.path.join(target_folder, "sample_floor_record.csv"), "w") as test_f:
            test_f.write("Item, Weight\nApples, 15kg\nOranges, 20kg\n")

    result = process_drive_folder(target_folder)
    print(result)