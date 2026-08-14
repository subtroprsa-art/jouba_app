import pandas as pd
from io import StringIO

# Paste the FIRST 5 lines of your actual floor CSV here (copy from your file)
TENAME	NAME	WHOLESALER	ODS_AGREE	DN_DATE_TIME	DN_DATE	SHORTSEQ	GRNID	PROD	LOC	QTY	PERID	TEID	QTY_AVAIL	QTY_SUSP	ORIGIN	RECTYPE	LU_ID	LOCATION	LOC_ID	COMMODITY	CONTAINER	VARIETY	CLASS	SIZ_REF	CNT_REF	COLOR	QTY_LATE	CF_CS_FLAG	CF_SORTING	CF_COMDTY_STRING	CF_DAYS_ON_FLOOR
R S A MARKET AGENTS	CHRISTOFF REINHARDT  DE WET			07-AUG-26	07-AUG-26	1796	15577136	A M MULLER EN SEU	HL 	64	82089	24	64	0		1	6	261	261	AVOS	SP180	AK	2	*	*	*		 	1796	AVOS,SP180,AK,CL 2,*,*,*	6
R S A MARKET AGENTS	CHRISTOFF REINHARDT  DE WET			07-AUG-26	07-AUG-26	5114	15577132	A M MULLER EN SEU	HL 	1	82089	24	1	0		1	6	261	261	AVOS	TR040	AH	1	*	18	*		 	5114	AVOS,TR040,AH,CL 1,*,18,*	6

try:
    # Try tab delimiter first
    df = pd.read_csv(StringIO(csv_sample), delimiter='\t')
    if len(df.columns) <= 1:
        df = pd.read_csv(StringIO(csv_sample), delimiter=',')
        
    print("✅ CSV read successfully!")
    print("\n📌 EXACT COLUMN NAMES FOUND IN YOUR CSV:")
    for i, col in enumerate(df.columns):
        print(f"Column {i+1}: '{col}'")
        
except Exception as e:
    print(f"❌ Error: {e}")