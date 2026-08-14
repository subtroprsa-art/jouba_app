import os
import re
import time
import requests
import pandas as pd
import psycopg2

from io import StringIO
from datetime import datetime
from psycopg2.extras import execute_values


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv(
    "TELEGRAM_CHANNEL_ID",
    "@JDW_Daily_files"
)

DATABASE_URL = os.getenv("DATABASE_URL")

STAGING_FOLDER = r"C:\project jouba\staging"

os.makedirs(
    STAGING_FOLDER,
    exist_ok=True
)

last_update_id = 0


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean_text(value):
    if pd.isna(value):
        return ""

    return str(value).strip()


def clean_int(value):
    if pd.isna(value) or value == "":
        return 0

    try:
        return int(float(value))

    except (ValueError, TypeError):
        return 0


def get_first(row, names, default=None):
    """
    Return the first matching non-null field.

    This lets the importer survive source-system
    header changes such as:

    GRN_NO / GRN / GRNID
    PRODUCER / WHOLESALER / PROD
    """

    for name in names:

        if (
            name in row.index
            and pd.notna(row[name])
        ):
            return row[name]

    return default


# ============================================================
# SALESMAN
# ============================================================

def parse_salesman(filename):

    name = filename.lower()

    if "cdw" in name:
        return "Christoff"

    if (
        "riaan" in name
        or "riaa" in name
    ):
        return "Riaan"

    if "pot" in name:
        return "Pot"

    return "Unassigned"


# ============================================================
# REPORT TYPE
# ============================================================

def parse_report_type(filename):

    name = filename.lower()

    if "stock" in name:
        return "stock"

    if "floor" in name:
        return "floor"

    return None


# ============================================================
# REPORT DATE
# ============================================================

def parse_report_date(filename):
    """
    Expected filename example:

    cdwstock13082026.csv
    potfloor13082026.csv

    Extracts:
    13/08/2026
    """

    match = re.search(
        r"(\d{2})(\d{2})(\d{4})",
        filename
    )

    if not match:
        return None

    day = int(match.group(1))
    month = int(match.group(2))
    year = int(match.group(3))

    try:

        return datetime(
            year,
            month,
            day
        ).date()

    except ValueError:
        return None


# ============================================================
# STAGING FILE NAME
# ============================================================

def staging_path(
    salesman,
    report_date,
    report_type
):

    safe_salesman = (
        salesman
        .lower()
        .replace(" ", "_")
    )

    date_text = report_date.strftime(
        "%Y%m%d"
    )

    filename = (
        f"{safe_salesman}_"
        f"{date_text}_"
        f"{report_type}.csv"
    )

    return os.path.join(
        STAGING_FOLDER,
        filename
    )


# ============================================================
# PRODUCT PARSER
# ============================================================

def parse_product(raw_product):
    """
    Market product layout:

    COMMODITY,
    PACKAGING,
    VARIETY,
    CLASS,
    SIZE,
    COUNT,
    OTHER

    Example:

    AVOS,TR040,AF,1,*,14,*
    """

    raw_product = clean_text(
        raw_product
    )

    parts = [
        p.strip()
        for p in raw_product.split(",")
    ]

    while len(parts) < 7:
        parts.append("*")

    commodity_code = parts[0]
    pack_code = parts[1]
    variety_code = parts[2]
    grade_code = parts[3]
    size_code = parts[4]
    count_code = parts[5]

    def remove_placeholder(value):

        if value == "*":
            return ""

        return value

    commodity_code = remove_placeholder(
        commodity_code
    )

    pack_code = remove_placeholder(
        pack_code
    )

    variety_code = remove_placeholder(
        variety_code
    )

    grade_code = remove_placeholder(
        grade_code
    )

    size_code = remove_placeholder(
        size_code
    )

    count_code = remove_placeholder(
        count_code
    )

    # --------------------------------------------------------
    # Confirmed commodity mappings
    # --------------------------------------------------------

    commodity_map = {

        "AVOS": "Avocados",

        "LEMS": "Lemons",

        "ORGS": "Oranges",

        "NAAR": "Naartjies",
    }

    # --------------------------------------------------------
    # Confirmed variety mappings
    # --------------------------------------------------------

    variety_map = {

        "AF": "Fuerte",

        "AK": "Pinkerton",

        "MA": "Maluma Hass",

        "MAH": "Maluma Hass",

        "NAR": "Nardocott",

        "NV": "Navel",

        "CN": "Cara Cara Navel",
    }

    # --------------------------------------------------------
    # Confirmed packaging mappings
    # --------------------------------------------------------

    pack_map = {

        "TR040": "Tray 4 kg",

        "BG150": "Bag 15 kg",

        "SP170": "Sugar Pocket 17 kg",

        "CO100": "Carton Open Top 10 kg",

        "CTT150": "Carton Closed Top 15 kg",

        "PC060": "Pocket 6 kg",
    }

    commodity = commodity_map.get(
        commodity_code,
        commodity_code
    )

    packaging = pack_map.get(
        pack_code,
        pack_code
    )

    variety = variety_map.get(
        variety_code,
        variety_code
    )

    # --------------------------------------------------------
    # Class normalization
    # --------------------------------------------------------

    grade = (
        grade_code
        .upper()
        .replace("CLASS", "")
        .replace("CL", "")
        .strip()
    )

    if grade:

        if grade == "12":
            grade = "Lowest Class"

        else:
            grade = f"Class {grade}"

    return {

        "raw_product": raw_product,

        "commodity": commodity,

        "pack": packaging,

        "variety": variety,

        "grade": grade,

        "size": size_code,

        "count": count_code,
    }


# ============================================================
# CSV READER
# ============================================================

def read_csv_data(content):

    csv_data = content.decode(
        "utf-8-sig"
    )

    # --------------------------------------------------------
    # First try TAB.
    # --------------------------------------------------------

    df = pd.read_csv(
        StringIO(csv_data),
        delimiter="\t",
        dtype=str
    )

    # --------------------------------------------------------
    # If it produced only one column,
    # try comma-separated.
    # --------------------------------------------------------

    if len(df.columns) <= 1:

        df = pd.read_csv(
            StringIO(csv_data),
            delimiter=",",
            dtype=str
        )

    # --------------------------------------------------------
    # Normalize source headings.
    # --------------------------------------------------------

    df.columns = [

        str(c)
        .strip()
        .upper()
        .replace(" ", "_")

        for c in df.columns
    ]

    return df


# ============================================================
# STOCK EQUATION
# ============================================================

def validate_stock_row(
    qty_rec,
    qty_sold,
    qty_floor,
    qty_coldstore,
    qty_reserved,
    qty_transit,
    qty_sort,
    qty_destroyed
):

    remaining = (
        qty_rec
        -
        qty_sold
    )

    accounted_for = (

        qty_floor
        +
        qty_coldstore
        +
        qty_reserved
        +
        qty_transit
        +
        qty_sort
        +
        qty_destroyed
    )

    difference = (
        remaining
        -
        accounted_for
    )

    return (
        difference == 0,
        difference
    )


# ============================================================
# BUILD STOCK DATA
# ============================================================

def build_stock_records(
    df,
    salesman
):

    records = []

    validation_errors = []

    floor_by_grn = {}

    reserved_by_grn = {}

    for row_number, (_, row) in enumerate(
        df.iterrows(),
        start=2
    ):

        grn = clean_text(
            get_first(
                row,
                [
                    "GRN_NO",
                    "GRN",
                    "GRNID"
                ],
                ""
            )
        )

        if not grn:
            continue

        # ----------------------------------------------------
        # Producer
        # ----------------------------------------------------

        producer = clean_text(
            get_first(
                row,
                [
                    "PRODUCER",
                    "WHOLESALER",
                    "PROD"
                ],
                ""
            )
        )

        # ----------------------------------------------------
        # Raw product code
        # ----------------------------------------------------

        raw_product = clean_text(
            get_first(
                row,
                [
                    "COMMODITY",
                    "PRODUCT"
                ],
                ""
            )
        )

        product = parse_product(
            raw_product
        )

        # ----------------------------------------------------
        # Quantities
        # ----------------------------------------------------

        qty_rec = clean_int(
            get_first(
                row,
                ["QTY_REC"],
                0
            )
        )

        qty_sold = clean_int(
            get_first(
                row,
                ["QTY_SOLD"],
                0
            )
        )

        qty_floor = clean_int(
            get_first(
                row,
                [
                    "QTY_FLOOR",
                    "FLR"
                ],
                0
            )
        )

        qty_coldstore = clean_int(
            get_first(
                row,
                [
                    "CSSUM",
                    "QTY_COLDSTORE",
                    "COLDSTORE"
                ],
                0
            )
        )

        qty_reserved = clean_int(
            get_first(
                row,
                [
                    "QTY_RESERVED",
                    "RESERVED"
                ],
                0
            )
        )

        qty_transit = clean_int(
            get_first(
                row,
                [
                    "ITSUM",
                    "QTY_TRANSIT",
                    "TRANSIT"
                ],
                0
            )
        )

        qty_sort = clean_int(
            get_first(
                row,
                [
                    "SSUM",
                    "QTY_SORT",
                    "SORTING"
                ],
                0
            )
        )

        qty_destroyed = clean_int(
            get_first(
                row,
                [
                    "DRQTY",
                    "QTY_DESTROYED"
                ],
                0
            )
        )

        # ----------------------------------------------------
        # Date
        # ----------------------------------------------------

        raw_date = get_first(
            row,
            [
                "DATE_RECEIVED",
                "DATE",
                "RECEIVED"
            ],
            None
        )

        date_received = None

        if raw_date:

            try:

                date_received = pd.to_datetime(
                    raw_date,
                    dayfirst=True
                ).date()

            except Exception:

                date_received = None

        # ----------------------------------------------------
        # Validate accounting equation
        # ----------------------------------------------------

        ok, difference = validate_stock_row(

            qty_rec,

            qty_sold,

            qty_floor,

            qty_coldstore,

            qty_reserved,

            qty_transit,

            qty_sort,

            qty_destroyed
        )

        if not ok:

            validation_errors.append({

                "row": row_number,

                "grn": grn,

                "difference": difference
            })

        floor_by_grn[grn] = (
            floor_by_grn.get(
                grn,
                0
            )
            +
            qty_floor
        )

        reserved_by_grn[grn] = (
            reserved_by_grn.get(
                grn,
                0
            )
            +
            qty_reserved
        )

        validation_message = (
            "OK"
            if ok
            else
            f"Stock equation difference: "
            f"{difference}"
        )

        # ----------------------------------------------------
        # Preserve ALL GRNs.
        #
        # Do NOT throw away coldstore-only stock.
        # ----------------------------------------------------

        records.append((

            salesman,

            grn,

            producer,

            product["commodity"],

            product["pack"],

            product["variety"],

            product["grade"],

            product["size"],

            product["count"],

            qty_rec,

            qty_sold,

            qty_floor,

            qty_coldstore,

            qty_reserved,

            qty_transit,

            qty_sort,

            qty_destroyed,

            product["raw_product"],

            ok,

            validation_message,

            date_received,

            # Legacy qty field currently used
            # by your Stock website.
            qty_floor
        ))

    return {

        "records": records,

        "errors": validation_errors,

        "floor_by_grn": floor_by_grn,

        "reserved_by_grn": reserved_by_grn
    }


# ============================================================
# BUILD FLOOR DATA
# ============================================================

def build_floor_records(
    df,
    salesman
):

    records = []

    hl_by_grn = {}

    reserved_by_grn = {}

    seqs_by_grn = {}

    other_locations = {}

    for _, row in df.iterrows():

        grn = clean_text(
            get_first(
                row,
                [
                    "GRNID",
                    "GRN",
                    "GRN_NO"
                ],
                ""
            )
        )

        if not grn:
            continue

        seq_nr = clean_int(
            get_first(
                row,
                [
                    "SHORTSEQ",
                    "SEQ",
                    "SEQ_NR",
                    "SEQ_NO"
                ],
                0
            )
        )

        producer = clean_text(
            get_first(
                row,
                [
                    "WHOLESALER",
                    "PROD",
                    "PRODUCER"
                ],
                ""
            )
        )

        commodity = clean_text(
            get_first(
                row,
                ["COMMODITY"],
                ""
            )
        )

        pack = clean_text(
            get_first(
                row,
                [
                    "CONTAINER",
                    "PACK",
                    "PACKING"
                ],
                ""
            )
        )

        variety = clean_text(
            get_first(
                row,
                ["VARIETY"],
                ""
            )
        )

        grade_raw = clean_text(
            get_first(
                row,
                [
                    "CLASS",
                    "GRADE"
                ],
                ""
            )
        )

        if grade_raw:

            if grade_raw == "12":
                grade = "Lowest Class"

            else:
                grade = f"Class {grade_raw}"

        else:
            grade = ""

        size = clean_text(
            get_first(
                row,
                [
                    "SIZ_REF",
                    "SIZE"
                ],
                ""
            )
        )

        count = clean_text(
            get_first(
                row,
                [
                    "CNT_REF",
                    "COUNT"
                ],
                ""
            )
        )

        location = clean_text(
            get_first(
                row,
                [
                    "LOC",
                    "LOCATION"
                ],
                ""
            )
        ).upper()

        # ====================================================
        # IMPORTANT
        #
        # QTY is the row's actual location balance.
        #
        # QTY_AVAIL is not always the same thing.
        #
        # Example:
        #
        # HL   = 57 available
        # HL R = 15 reserved
        #
        # The HL R row can still contain
        # QTY_AVAIL = 57.
        # ====================================================

        qty = clean_int(
            get_first(
                row,
                [
                    "QTY",
                    "BALANCE",
                    "QTY_AVAIL"
                ],
                0
            )
        )

        raw_date = get_first(
            row,
            [
                "DN_DATE",
                "DATE_RECEIVED",
                "RECEIVED"
            ],
            None
        )

        date_received = None

        if raw_date:

            try:

                date_received = pd.to_datetime(
                    raw_date,
                    dayfirst=True
                ).date()

            except Exception:

                date_received = None

        # ----------------------------------------------------
        # Keep non-zero location rows.
        # ----------------------------------------------------

        if qty == 0:
            continue

        records.append((

            salesman,

            seq_nr,

            grn,

            producer,

            commodity,

            pack,

            variety,

            grade,

            size,

            count,

            qty,

            # Temporary use of existing
            # floor_records.coldstore field
            # to store location code.
            location,

            date_received
        ))

        # ----------------------------------------------------
        # HL = ordinary floor stock
        # ----------------------------------------------------

        if location == "HL":

            hl_by_grn[grn] = (
                hl_by_grn.get(
                    grn,
                    0
                )
                +
                qty
            )

            if seq_nr:

                seqs_by_grn.setdefault(
                    grn,
                    []
                ).append(
                    (
                        seq_nr,
                        qty
                    )
                )

        # ----------------------------------------------------
        # HL R = reserved floor stock
        # ----------------------------------------------------

        elif location == "HL R":

            reserved_by_grn[grn] = (
                reserved_by_grn.get(
                    grn,
                    0
                )
                +
                qty
            )

        # ----------------------------------------------------
        # Everything else:
        #
        # AC
        # MC6
        # TR
        # etc.
        #
        # Keep it, but do not use it for
        # normal floor reconciliation.
        # ----------------------------------------------------

        else:

            if location:

                key = (
                    grn,
                    location
                )

                other_locations[key] = (
                    other_locations.get(
                        key,
                        0
                    )
                    +
                    qty
                )

    return {

        "records": records,

        "hl_by_grn": hl_by_grn,

        "reserved_by_grn": reserved_by_grn,

        "seqs_by_grn": seqs_by_grn,

        "other_locations": other_locations
    }


# ============================================================
# CROSS-FILE VALIDATION
# ============================================================

def validate_pair(
    stock_data,
    floor_data
):

    problems = []

    # --------------------------------------------------------
    # Stock equation
    # --------------------------------------------------------

    if stock_data["errors"]:

        for error in stock_data["errors"]:

            problems.append(
                "Stock equation failed for "
                f"GRN {error['grn']} "
                f"(difference "
                f"{error['difference']})"
            )

    # --------------------------------------------------------
    # QTY_FLOOR versus Floor Balance HL
    # --------------------------------------------------------

    stock_floor = (
        stock_data["floor_by_grn"]
    )

    floor_hl = (
        floor_data["hl_by_grn"]
    )

    all_grns = (
        set(stock_floor)
        |
        set(floor_hl)
    )

    floor_mismatches = []

    for grn in sorted(all_grns):

        stock_qty = stock_floor.get(
            grn,
            0
        )

        floor_qty = floor_hl.get(
            grn,
            0
        )

        if stock_qty != floor_qty:

            floor_mismatches.append(
                (
                    grn,
                    stock_qty,
                    floor_qty
                )
            )

    for (
        grn,
        stock_qty,
        floor_qty
    ) in floor_mismatches:

        problems.append(
            f"Floor mismatch GRN {grn}: "
            f"Stock={stock_qty}, "
            f"HL={floor_qty}"
        )

    # --------------------------------------------------------
    # Reserved validation
    #
    # Only compare GRNs where either side
    # reports a reservation.
    # --------------------------------------------------------

    stock_reserved = (
        stock_data[
            "reserved_by_grn"
        ]
    )

    floor_reserved = (
        floor_data[
            "reserved_by_grn"
        ]
    )

    reservation_grns = (
        set(
            grn
            for grn, qty
            in stock_reserved.items()
            if qty > 0
        )
        |
        set(
            grn
            for grn, qty
            in floor_reserved.items()
            if qty > 0
        )
    )

    for grn in reservation_grns:

        stock_qty = stock_reserved.get(
            grn,
            0
        )

        floor_qty = floor_reserved.get(
            grn,
            0
        )

        if stock_qty != floor_qty:

            problems.append(
                f"Reserved mismatch GRN {grn}: "
                f"Stock={stock_qty}, "
                f"HL R={floor_qty}"
            )

    # --------------------------------------------------------
    # Grand totals
    # --------------------------------------------------------

    stock_floor_total = sum(
        stock_floor.values()
    )

    floor_hl_total = sum(
        floor_hl.values()
    )

    print("")
    print(
        f"Stock QTY_FLOOR total : "
        f"{stock_floor_total:,}"
    )

    print(
        f"Floor HL total        : "
        f"{floor_hl_total:,}"
    )

    # --------------------------------------------------------
    # Multiple SEQs
    # --------------------------------------------------------

    multiple_seqs = {

        grn: seqs

        for grn, seqs
        in floor_data[
            "seqs_by_grn"
        ].items()

        if len(seqs) > 1
    }

    if multiple_seqs:

        print("")
        print(
            "ℹ️ GRNs with multiple SEQs:"
        )

        for grn, seqs in multiple_seqs.items():

            print(
                f"   {grn}: {seqs}"
            )

    # --------------------------------------------------------
    # Other locations
    # --------------------------------------------------------

    location_totals = {}

    for (
        grn,
        location
    ), qty in floor_data[
        "other_locations"
    ].items():

        location_totals[location] = (
            location_totals.get(
                location,
                0
            )
            +
            qty
        )

    if location_totals:

        print("")
        print(
            "ℹ️ Other Floor locations:"
        )

        for (
            location,
            qty
        ) in sorted(
            location_totals.items()
        ):

            print(
                f"   {location}: "
                f"{qty:,}"
            )

    return (
        len(problems) == 0,
        problems
    )


# ============================================================
# PROCESSED FILES
# ============================================================

def is_pair_already_processed(
    conn,
    pair_key
):

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM processed_files
        WHERE filename = %s
        """,
        (
            pair_key,
        )
    )

    result = cursor.fetchone()

    cursor.close()

    return result is not None


def mark_pair_processed(
    conn,
    pair_key
):

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO processed_files
        (filename)
        VALUES (%s)
        """,
        (
            pair_key,
        )
    )

    cursor.close()


# ============================================================
# DATABASE REPLACEMENT
# ============================================================

def replace_snapshot(
    conn,
    salesman,
    stock_records,
    floor_records
):

    cursor = conn.cursor()

    try:

        # ====================================================
        # Delete previous snapshot for salesman
        # ONLY AFTER ALL VALIDATION PASSED.
        # ====================================================

        cursor.execute(
            """
            DELETE FROM floor_records
            WHERE salesman = %s
            """,
            (
                salesman,
            )
        )

        cursor.execute(
            """
            DELETE FROM stock_records
            WHERE salesman = %s
            """,
            (
                salesman,
            )
        )

        # ====================================================
        # STOCK
        # ====================================================

        stock_insert = """
            INSERT INTO stock_records
            (
                salesman,
                grn,
                producer,
                commodity,
                pack,
                variety,
                grade,
                size,
                count,
                qty_rec,
                qty_sold,
                qty_floor,
                qty_coldstore,
                qty_reserved,
                qty_transit,
                qty_sort,
                qty_destroyed,
                raw_product_code,
                validation_ok,
                validation_message,
                date_received,
                qty
            )
            VALUES %s
        """

        execute_values(
            cursor,
            stock_insert,
            stock_records
        )

        # ====================================================
        # FLOOR
        # ====================================================

        floor_insert = """
            INSERT INTO floor_records
            (
                salesman,
                seq_nr,
                grn,
                producer,
                commodity,
                pack,
                variety,
                grade,
                size,
                count,
                qty,
                coldstore,
                date_received
            )
            VALUES %s
        """

        execute_values(
            cursor,
            floor_insert,
            floor_records
        )

    finally:

        cursor.close()


# ============================================================
# PROCESS MATCHED PAIR
# ============================================================

def process_staged_pair(
    salesman,
    report_date,
    stock_path,
    floor_path
):

    print("")
    print("=" * 70)

    print(
        f"🔎 Validating matched pair: "
        f"{salesman} "
        f"{report_date}"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # Read both files before touching Neon.
    # --------------------------------------------------------

    with open(
        stock_path,
        "rb"
    ) as f:

        stock_df = read_csv_data(
            f.read()
        )

    with open(
        floor_path,
        "rb"
    ) as f:

        floor_df = read_csv_data(
            f.read()
        )

    print(
        f"📦 Stock rows: "
        f"{len(stock_df)}"
    )

    print(
        f"🏬 Floor rows: "
        f"{len(floor_df)}"
    )

    # --------------------------------------------------------
    # Build normalized records
    # --------------------------------------------------------

    stock_data = build_stock_records(
        stock_df,
        salesman
    )

    floor_data = build_floor_records(
        floor_df,
        salesman
    )

    # --------------------------------------------------------
    # Validate both against one another
    # --------------------------------------------------------

    valid, problems = validate_pair(
        stock_data,
        floor_data
    )

    if not valid:

        print("")
        print("❌ PAIR VALIDATION FAILED")
        print("------------------------------")

        for problem in problems[:30]:

            print(
                f"   {problem}"
            )

        print("------------------------------")

        print(
            "⚠️ Existing Neon data "
            "has NOT been changed."
        )

        return False

    print("")
    print("✅ Stock equation passed")

    print(
        "✅ Every GRN floor quantity "
        "reconciles"
    )

    print(
        "✅ Reserved quantities reconcile"
    )

    # --------------------------------------------------------
    # Now DB credentials are required.
    # --------------------------------------------------------

    if not DATABASE_URL:

        print(
            "❌ DATABASE_URL "
            "environment variable missing."
        )

        return False

    pair_key = (
        f"PAIR:"
        f"{salesman}:"
        f"{report_date.isoformat()}"
    )

    conn = None

    try:

        conn = psycopg2.connect(
            DATABASE_URL
        )

        if is_pair_already_processed(
            conn,
            pair_key
        ):

            print(
                "⏭️ This salesman/date pair "
                "has already been processed."
            )

            return True

        # ====================================================
        # ONE DATABASE TRANSACTION
        #
        # Delete + Stock Insert + Floor Insert
        # all succeed together or none happen.
        # ====================================================

        replace_snapshot(

            conn,

            salesman,

            stock_data["records"],

            floor_data["records"]
        )

        mark_pair_processed(
            conn,
            pair_key
        )

        conn.commit()

        print("")
        print(
            f"✅ Loaded "
            f"{len(stock_data['records'])} "
            f"stock GRNs"
        )

        print(
            f"✅ Loaded "
            f"{len(floor_data['records'])} "
            f"floor/location rows"
        )

        print("")
        print(
            f"🎉 {salesman} snapshot "
            f"successfully updated."
        )

        # ----------------------------------------------------
        # Successful import:
        # remove staged source files.
        # ----------------------------------------------------

        try:
            os.remove(
                stock_path
            )

        except Exception:
            pass

        try:
            os.remove(
                floor_path
            )

        except Exception:
            pass

        return True

    except Exception as e:

        if conn:
            conn.rollback()

        print("")
        print(
            f"❌ DATABASE ERROR: {e}"
        )

        import traceback
        traceback.print_exc()

        print(
            "⚠️ Previous snapshot retained."
        )

        return False

    finally:

        if conn:
            conn.close()


# ============================================================
# STAGE INCOMING TELEGRAM FILE
# ============================================================

def stage_file(
    content,
    file_name
):

    salesman = parse_salesman(
        file_name
    )

    report_type = parse_report_type(
        file_name
    )

    report_date = parse_report_date(
        file_name
    )

    if salesman == "Unassigned":

        print(
            f"❌ Cannot identify salesman: "
            f"{file_name}"
        )

        return

    if not report_type:

        print(
            f"❌ Cannot identify Stock/Floor: "
            f"{file_name}"
        )

        return

    if not report_date:

        print(
            f"❌ Cannot identify report date: "
            f"{file_name}"
        )

        return

    destination = staging_path(

        salesman,

        report_date,

        report_type
    )

    with open(
        destination,
        "wb"
    ) as f:

        f.write(
            content
        )

    print("")
    print(
        f"📥 Staged {report_type.upper()} "
        f"for {salesman} "
        f"{report_date}"
    )

    # --------------------------------------------------------
    # Look for matching report
    # --------------------------------------------------------

    stock_path = staging_path(

        salesman,

        report_date,

        "stock"
    )

    floor_path = staging_path(

        salesman,

        report_date,

        "floor"
    )

    stock_exists = os.path.exists(
        stock_path
    )

    floor_exists = os.path.exists(
        floor_path
    )

    if (
        stock_exists
        and
        floor_exists
    ):

        print(
            "🔗 Matching Stock + Floor "
            "pair found."
        )

        process_staged_pair(

            salesman,

            report_date,

            stock_path,

            floor_path
        )

    else:

        if not stock_exists:

            print(
                "⏳ Waiting for matching "
                "Stock CSV..."
            )

        if not floor_exists:

            print(
                "⏳ Waiting for matching "
                "Floor CSV..."
            )


# ============================================================
# DOWNLOAD TELEGRAM FILE
# ============================================================

def download_telegram_file(
    file_id,
    file_name
):

    file_info_url = (

        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/getFile"
        f"?file_id={file_id}"
    )

    response = requests.get(
        file_info_url,
        timeout=30
    )

    response.raise_for_status()

    file_data = response.json()

    if not file_data.get("ok"):

        raise RuntimeError(
            "Telegram getFile failed"
        )

    telegram_path = (
        file_data[
            "result"
        ][
            "file_path"
        ]
    )

    download_url = (

        f"https://api.telegram.org/"
        f"file/bot{BOT_TOKEN}/"
        f"{telegram_path}"
    )

    download_response = requests.get(
        download_url,
        timeout=60
    )

    download_response.raise_for_status()

    print(
        f"✅ Downloaded {file_name}"
    )

    return download_response.content


# ============================================================
# TELEGRAM WATCHER
# ============================================================

def watch_telegram():

    global last_update_id

    if not BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN "
            "environment variable missing."
        )

        return

    print("")
    print(
        "👀 JDW Telegram Watcher started"
    )

    print(
        "Waiting for Stock/Floor CSV pairs..."
    )

    print("")

    while True:

        try:

            url = (

                f"https://api.telegram.org/"
                f"bot{BOT_TOKEN}/getUpdates"
                f"?offset={last_update_id + 1}"
                f"&timeout=30"
            )

            response = requests.get(
                url,
                timeout=40
            )

            if response.status_code != 200:

                print(
                    f"⚠️ Telegram returned "
                    f"{response.status_code}"
                )

                time.sleep(5)

                continue

            data = response.json()

            if not data.get("ok"):

                time.sleep(5)

                continue

            for update in data.get(
                "result",
                []
            ):

                last_update_id = (
                    update[
                        "update_id"
                    ]
                )

                post = update.get(
                    "channel_post"
                )

                if not post:
                    continue

                document = post.get(
                    "document"
                )

                if not document:
                    continue

                file_name = document.get(
                    "file_name",
                    ""
                )

                if not file_name.lower().endswith(
                    ".csv"
                ):
                    continue

                print("")
                print(
                    f"📨 Telegram detected: "
                    f"{file_name}"
                )

                file_id = document[
                    "file_id"
                ]

                content = download_telegram_file(

                    file_id,

                    file_name
                )

                stage_file(

                    content,

                    file_name
                )

        except KeyboardInterrupt:

            print("")
            print(
                "Watcher stopped."
            )

            break

        except Exception as e:

            print("")
            print(
                f"⚠️ Watcher error: {e}"
            )

            import traceback
            traceback.print_exc()

            time.sleep(5)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    watch_telegram()