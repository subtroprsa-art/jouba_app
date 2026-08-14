import os
import shutil
from datetime import date

from telegram_watcher import (
    STAGING_FOLDER,
    staging_path,
    read_csv_data,
    build_stock_records,
    build_floor_records,
    validate_pair
)

SALESMAN = "Christoff"
REPORT_DATE = date(2026, 8, 13)

SOURCE_STOCK = r"C:\project jouba\daily_uploads\cdwstock13082026.csv"
SOURCE_FLOOR = r"C:\project jouba\daily_uploads\cdwfloor13082026.csv"


def clear_test_files():
    for report_type in ["stock", "floor"]:
        path = staging_path(
            SALESMAN,
            REPORT_DATE,
            report_type
        )

        if os.path.exists(path):
            os.remove(path)


def load_csv(path):
    with open(path, "rb") as f:
        return read_csv_data(f.read())


def validate_staged_pair(stock_path, floor_path):
    stock_df = load_csv(stock_path)
    floor_df = load_csv(floor_path)

    stock_data = build_stock_records(
        stock_df,
        SALESMAN
    )

    floor_data = build_floor_records(
        floor_df,
        SALESMAN
    )

    valid, problems = validate_pair(
        stock_data,
        floor_data
    )

    if valid:
        print("🎉 STAGED PAIR VALIDATION: PASS")
    else:
        print("❌ STAGED PAIR VALIDATION: FAIL")

        for problem in problems:
            print(f"   {problem}")


def main():
    clear_test_files()

    stock_stage = staging_path(
        SALESMAN,
        REPORT_DATE,
        "stock"
    )

    floor_stage = staging_path(
        SALESMAN,
        REPORT_DATE,
        "floor"
    )

    print("\n1. Simulating STOCK arriving first...")

    shutil.copyfile(
        SOURCE_STOCK,
        stock_stage
    )

    print(f"✅ Stock staged: {stock_stage}")

    if os.path.exists(floor_stage):
        print("❌ Unexpected Floor file already exists.")
    else:
        print("⏳ Correct: waiting for Floor file.")

    print("\n2. Simulating FLOOR arriving second...")

    shutil.copyfile(
        SOURCE_FLOOR,
        floor_stage
    )

    print(f"✅ Floor staged: {floor_stage}")

    if (
        os.path.exists(stock_stage)
        and os.path.exists(floor_stage)
    ):
        print("🔗 Matching pair detected.")
        validate_staged_pair(
            stock_stage,
            floor_stage
        )
    else:
        print("❌ Pair detection failed.")


if __name__ == "__main__":
    main()