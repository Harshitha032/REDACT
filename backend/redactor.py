"""
redactor.py  —  Redactify Detection & Redaction Engine  (FIXED v3)

Key fixes:
  - Indian single-word ALL-CAPS names detected (HARSHITHA, BAVYASHREE, LAKSHANYA)
  - Short/informal names detected (harshi, harshu, Harshi, Bavyashree)
  - Live preview uses same engine — all names redacted consistently
  - Reduced false positives via refined blocklists
  - spaCy used as primary, robust regex as strong fallback

Redaction levels:
  1  →  XXXXX           (same character count)
  2  →  Person 1        (sequential labels, consistent)
  3  →  Priya Kumar     (realistic fake data)
"""

import re
import random

# ── spaCy ──────────────────────────────────────────────────────────────────────
try:
    import spacy
    _nlp = None
    for _m in ("en_core_web_lg", "en_core_web_md", "en_core_web_sm"):
        try:
            _nlp = spacy.load(_m)
            print(f"[Redactor] spaCy model: {_m}")
            break
        except OSError:
            continue
    if _nlp is None:
        print("[Redactor] No spaCy model — install with: python -m spacy download en_core_web_sm")
    SPACY_OK = _nlp is not None
except ImportError:
    SPACY_OK = False
    _nlp = None
    print("[Redactor] spaCy not installed — using regex-only mode.")

# ── Faker ──────────────────────────────────────────────────────────────────────
try:
    from faker import Faker as _Faker
    _fake = _Faker("en_IN")
    FAKER_OK = True
except ImportError:
    FAKER_OK = False

# ══════════════════════════════════════════════════════════════════════════════
# KNOWN INDIAN NAMES — Single word names that should always be redacted
# These are common South Indian / Indian names that regex might miss
# ══════════════════════════════════════════════════════════════════════════════
KNOWN_INDIAN_NAMES = {
    # South Indian female names
    "harshitha","harshi","harshu","bavyashree","bavya","lakshanya","lakshmi",
    "lakshanya","saranya","saranya","kavya","kavitha","ananya","ananya",
    "divya","deepa","priya","pooja","sneha","swathi","rekha","meena",
    "padma","hema","jaya","uma","savita","lalita","beena","devi","nisha",
    "esha","anita","sangeetha","sangitha","vaishnavi","varshini","keerthi",
    "keerthana","kirthana","kirthika","karthika","dharshini","dharshitha",
    "nandhini","nandhitha","janani","jayanthi","jayalakshmi","mythili",
    "mythri","nithya","nithyashree","pavithra","priyadharshini","ramya",
    "revathi","rohini","sabitha","sahana","saraswathi","shalini","shanthi",
    "shobha","sindhu","sirisha","sowmya","sridevi","sujatha","sumithra",
    "sunitha","supriya","surekha","sushmitha","swetha","tamilselvi","thenmozhi",
    "umamaheswari","usha","vanitha","vasantha","vasuki","vimala","yamini",
    "yazhini","yasodha","yuvarani","zara","ranjitha","ranjani","radhika",
    "padmalatha","nagalakshmi","meenakshi","mahalakshmi","kamala","indrani",
    "gayathri","gayatri","geetha","geethanjali","hemavathi","indumathi",
    # South Indian male names
    "arjun","rohan","karthik","aditya","rahul","sanjay","vijay","nikhil",
    "harish","suresh","ganesh","vikram","ashok","chetan","farhan","girish",
    "ishaan","mohan","om","ravi","tarun","varun","waqar","xavier","yash",
    "karthikeyan","murugan","senthil","selvam","surya","tamilarasan",
    "vignesh","vinoth","vishnu","yuvraj","yuvan","balaji","bharath",
    "dhanush","dinesh","ezhil","gowtham","guru","harikrishnan","hari",
    "harshavardhan","jagadeesh","jagadish","jeevan","jegadeesh","kathir",
    "kumaran","lokesh","madhan","manikandan","maran","mugesh","nithish",
    "prabhu","praveen","premkumar","prithviraj","pugazh","raghu","rajesh",
    "rakesh","ramesh","ranjith","ravi","saravanan","sathish","selvaraj",
    "sivaraman","soundar","soundararajan","sudhakar","sugumar","sundaram",
    "surendran","suriyaprakash","thirumurugan","thyagarajan","udhayakumar",
    "vasanth","venkatesh","venkataraman","vigneshwaran","vijayakumar",
    # Common North Indian names
    "amit","ankit","ankur","anurag","arpit","ashish","devesh","dhruv",
    "gaurav","harsh","hemant","hitesh","jatin","kamal","kapil","lalit",
    "manish","mukesh","naveen","nitin","pankaj","paresh","parth","piyush",
    "prakash","prateek","puneet","rajat","rajiv","ramesh","ritesh","rohit",
    "sachin","sameer","sandeep","saurabh","shiv","shubham","siddharth",
    "soham","subhash","sumit","sunil","suresh","tarun","umesh","utsav",
    "vikas","vivek","yogesh","aakash","aarav","abhijit","abhishek","abhinav",
    "aishwarya","akash","akanksha","akshata","akshay","alok","aman","amitabh",
    "amrita","anand","ankita","aparajita","archana","aryan","ashwini","avni",
}

# ══════════════════════════════════════════════════════════════════════════════
# FALSE-POSITIVE BLOCKLIST
# ══════════════════════════════════════════════════════════════════════════════
NON_PERSON_WORDS = {
    # CV / resume section headings
    "objective","summary","experience","education","skills","projects",
    "references","declaration","profile","contact","address","hobbies",
    "internship","training","certification","achievement","award","resume",
    "curriculum","vitae","cgpa","gpa","percentage","marks","duration",
    "languages","interests","activities","publications","responsibilities",
    "overview","highlights","qualifications","accomplishments","portfolio",
    "volunteer","extracurricular","coursework","relevant","technical",
    # Job titles / roles
    "engineer","developer","manager","analyst","architect","designer",
    "consultant","director","officer","executive","associate","specialist",
    "coordinator","supervisor","lead","intern","trainee","researcher",
    "scientist","administrator","assistant","representative","head",
    "software","senior","junior","principal","staff","deputy","advisor",
    "strategist","planner","auditor","accountant","attorney","counsel",
    # Education
    "university","college","institute","school","academy","institution",
    "iit","nit","bits","vit","srm","mit","engineering","polytechnic",
    "deemed","autonomous","faculty","department","campus","affiliated",
    "bachelor","master","doctorate","diploma","undergraduate","graduate",
    "science","computer","information","mechanical","electrical","civil",
    "commerce","arts","management","business","administration","technology",
    # Company / org keywords
    "technologies","solutions","services","systems","corporation","corp",
    "limited","ltd","pvt","inc","llc","foundation","trust","association",
    "bank","hospital","clinic","centre","center","ministry","government",
    "group","enterprises","industries","ventures","company","startup",
    "organization","organisation","agency","bureau","authority","board",
    # Address / location words
    "street","road","avenue","nagar","colony","district","city","state",
    "country","building","tower","complex","plaza","mall","park","floor",
    "wing","block","sector","village","taluk","mandal","zone","lane",
    "india","indian","chennai","mumbai","delhi","bangalore","bengaluru",
    "hyderabad","pune","kolkata","ahmedabad","jaipur","lucknow","tamil",
    "karnataka","maharashtra","gujarat","rajasthan","kerala","andhra",
    # Months & days
    "january","february","march","april","june","july","august",
    "september","october","november","december",
    "monday","tuesday","wednesday","thursday","friday","saturday","sunday",
    # Common words
    "the","and","for","with","from","this","that","then","than","when",
    "where","which","while","about","above","below","after","before",
    "during","between","through","without","within","against","toward",
    # Abbreviations / titles
    "hr","ceo","cto","cfo","vp","svp","avp","gm","dm","pm","dob",
    "pan","uan","epf","esi","tds","gst","mrp","etc","ref","attn",
    # Document words
    "page","date","time","year","month","day","serial","number","total",
    "amount","balance","credit","debit","invoice","receipt","order",
    "present","current","ongoing","till","period",
    "subject","regarding","dear","sincerely","yours","truly","regards",
    # Indian-specific false positives
    "anna","national","international","global","regional","local",
    "public","private","central","district","municipal",
}

# ALL-CAPS skip list
_CAPS_SKIP = {
    "DOB","PAN","UAN","EPF","ESI","TDS","GST","MRP","ETC","REF","ATTN",
    "HR","CEO","CTO","CFO","VP","SVP","AVP","GM","DM","PM","ID","NA",
    "THE","AND","FOR","WITH","FROM","THIS","THAT","THEN","THAN","WHEN",
    "DATE","TIME","PAGE","NAME","MALE","FEMALE","NULL","TRUE","FALSE",
    "CGPA","GPA","MBA","BBA","BCA","MCA","BSC","MSC","PHD","BE","ME",
    "INDIA","TAMIL","HINDI","ENGLISH","KANNADA","TELUGU","BENGALI",
    "JANUARY","FEBRUARY","MARCH","APRIL","JUNE","JULY","AUGUST",
    "SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER",
    "MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY",
    "OBJECTIVE","SUMMARY","EXPERIENCE","EDUCATION","SKILLS","PROJECTS",
    "REFERENCES","DECLARATION","PROFILE","CONTACT","ADDRESS","HOBBIES",
    "INTERNSHIP","TRAINING","CERTIFICATION","ACHIEVEMENT","AWARD","RESUME",
    "LANGUAGES","INTERESTS","ACTIVITIES","PUBLICATIONS","WORK","PERSONAL",
    "DETAILS","INFORMATION","ACADEMIC","PROFESSIONAL","TECHNICAL","OTHER",
    "TOTAL","AMOUNT","BALANCE","CREDIT","DEBIT","INVOICE","SUBJECT",
}

def _is_non_person(text: str) -> bool:
    lower = text.lower().strip()
    words = lower.split()
    for w in words:
        clean_w = w.strip(".,;:()")
        if clean_w in NON_PERSON_WORDS:
            return True
    if any(c.isdigit() for c in text):
        return True
    if any(len(w.strip(".,;:()")) <= 1 for w in words):
        return True
    return False

def _is_known_indian_name(text: str) -> bool:
    """Check if text (or any word in it) is a known Indian name."""
    lower = text.lower().strip()
    if lower in KNOWN_INDIAN_NAMES:
        return True
    # Check each word
    for word in lower.split():
        clean = word.strip(".,;:()")
        if clean in KNOWN_INDIAN_NAMES:
            return True
    return False

def _looks_like_name(text: str) -> bool:
    words = text.strip().split()
    if len(words) < 1 or len(words) > 5:
        return False
    for w in words:
        clean = w.strip(".,;:()")
        if not (2 <= len(clean) <= 25):
            return False
        if not clean.isalpha():
            return False
    return True

def _is_caps_abbreviation(text: str) -> bool:
    for w in text.split():
        if w in _CAPS_SKIP:
            return True
    return False

# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURED DATA PATTERNS
# ══════════════════════════════════════════════════════════════════════════════
PATTERNS = {
    "EMAIL"      : r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
    "PHONE"      : r'(?<!\d)(\+91[\s\-]?)?[6-9]\d{9}(?!\d)',
    "AADHAAR"    : r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b',
    "PAN"        : r'\b[A-Z]{5}[0-9]{4}[A-Z]\b',
    "DOB"        : r'\b(?:\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})\b',
    "PINCODE"    : r'(?<!\d)[1-9][0-9]{5}(?!\d)',
    "PASSPORT"   : r'\b[A-PR-WY][1-9]\d\s?\d{4}[1-9]\b',
    "CREDIT_CARD": r'\b(?:\d[ \-]?){15,16}\b',
    "URL"        : r'https?://[^\s<>"]+',
    "LINKEDIN"   : r'linkedin\.com/in/[A-Za-z0-9\-_%]+',
    "GITHUB"     : r'github\.com/[A-Za-z0-9\-_%]+',
    "IP"         : r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
}

# ALL-CAPS name: 1+ words all uppercase (also catches single-word ALL-CAPS names)
_CAPS_NAME = re.compile(
    r'\b([A-Z]{3,20}(?:[ \t]+[A-Z]{3,20}){0,3})\b'
)

# Title-case names (with optional honorifics)
_TITLE_NAME = re.compile(
    r'\b(?:(?:Dr|Mr|Mrs|Ms|Prof|Sri|Smt|Shri)\.?\s+)?([A-Z][a-z]{2,19}(?:[ \t]+[A-Z][a-z]{2,19}){0,3})\b'
)

# lowercase known name pattern — catches informal names like harshi, harshu
# This is only checked against KNOWN_INDIAN_NAMES
_LOWER_NAME = re.compile(r'\b([a-z]{3,20})\b')

# Name field label pattern — catches "Name: Harshi" or "name - bavyashree"
_NAME_FIELD = re.compile(
    r'(?:name|student|candidate|applicant|employee|patient|customer|member|resident)\s*[:=\-–]\s*([A-Za-z][A-Za-z\s]{1,40})',
    re.IGNORECASE
)

# ══════════════════════════════════════════════════════════════════════════════
# FAKE DATA
# ══════════════════════════════════════════════════════════════════════════════
_FF = ["Arjun","Priya","Rohan","Kavya","Vikram","Ananya","Karthik","Sneha",
       "Aditya","Pooja","Rahul","Divya","Sanjay","Meena","Vijay","Lakshmi",
       "Nikhil","Swathi","Harish","Deepa","Suresh","Rekha","Ganesh","Saranya"]
_FL = ["Kumar","Sharma","Patel","Reddy","Nair","Iyer","Singh","Verma",
       "Gupta","Joshi","Pillai","Menon","Rao","Mishra","Das","Bose"]
_FC = ["Mumbai","Delhi","Bengaluru","Hyderabad","Pune",
       "Ahmedabad","Kolkata","Jaipur","Bhopal","Coimbatore"]
_FD = ["gmail.com","yahoo.com","outlook.com","protonmail.com"]

def _fn():   return f"{random.choice(_FF)} {random.choice(_FL)}"
def _fe():   return f"{random.choice(_FF).lower()}{random.randint(10,99)}@{random.choice(_FD)}"
def _fp():   return f"{random.choice([6,7,8,9])}{''.join(str(random.randint(0,9)) for _ in range(9))}"
def _fa():   return " ".join("".join(str(random.randint(0,9)) for _ in range(4)) for _ in range(3))
def _fpan():
    L="ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(random.choices(L,k=5))+"".join(str(random.randint(0,9)) for _ in range(4))+random.choice(L)
def _fd():   return f"{random.randint(1,28):02d}/{random.randint(1,12):02d}/{random.randint(1970,2003)}"

_FAKE = {
    "PERSON"      : _fn,
    "EMAIL"       : _fe,
    "PHONE"       : _fp,
    "AADHAAR"     : _fa,
    "PAN"         : _fpan,
    "DOB"         : _fd,
    "PINCODE"     : lambda: str(random.randint(100000,999999)),
    "LOCATION"    : lambda: random.choice(_FC),
    "PASSPORT"    : lambda: f"Z{random.randint(1000000,9999999)}",
    "CREDIT_CARD" : lambda: " ".join("".join(str(random.randint(0,9)) for _ in range(4)) for _ in range(4)),
    "IP"          : lambda: ".".join(str(random.randint(1,254)) for _ in range(4)),
    "URL"         : lambda: "https://example.com",
    "LINKEDIN"    : lambda: "linkedin.com/in/anonymous-user",
    "GITHUB"      : lambda: "github.com/anonymous-user",
    "CUSTOM"      : lambda: "REDACTED",
}

_LABELS = {
    "PERSON":"Person","EMAIL":"Email","PHONE":"Number","AADHAAR":"Aadhar",
    "PAN":"PAN","DOB":"DOB","LOCATION":"Location","PINCODE":"Pincode",
    "PASSPORT":"Passport","CREDIT_CARD":"Card","IP":"IP",
    "URL":"URL","LINKEDIN":"Profile","GITHUB":"Profile","CUSTOM":"Custom",
}

def _mask(val: str) -> str:
    return "".join("X" if c.isalnum() else c for c in val)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CLASS
# ══════════════════════════════════════════════════════════════════════════════
class Redactor:

    def detect_entities(self, text: str) -> list:
        found = []
        seen  = set()   # (start, end) already claimed

        # ── A. Structured patterns (email, phone, Aadhaar…) ──────────────────
        for label, pat in PATTERNS.items():
            for m in re.finditer(pat, text, re.IGNORECASE):
                key = (m.start(), m.end())
                if key not in seen:
                    seen.add(key)
                    found.append(self._ent(m.group(), label, m.start(), m.end(), "regex"))

        # ── B. Name field labels — "Name: Harshitha" ─────────────────────────
        for m in _NAME_FIELD.finditer(text):
            val = m.group(1).strip().rstrip(".,;")
            if len(val) < 2 or _is_non_person(val):
                continue
            # Extract just the name part (first 1-3 words)
            words = val.split()[:4]
            name_val = " ".join(words).strip()
            if not name_val or len(name_val) < 2:
                continue
            key = (m.start(1), m.start(1) + len(name_val))
            if key not in seen:
                seen.add(key)
                found.append(self._ent(name_val, "PERSON", m.start(1), m.start(1) + len(name_val), "field"))

        # ── C. spaCy NER ──────────────────────────────────────────────────────
        spacy_spans = set()
        if SPACY_OK and _nlp:
            doc = _nlp(text[:500_000])
            for ent in doc.ents:
                val = ent.text.strip()
                if ent.label_ == "PERSON":
                    if len(val) < 2:
                        continue
                    if _is_non_person(val):
                        continue
                    key = (ent.start_char, ent.end_char)
                    if key not in seen:
                        seen.add(key)
                        spacy_spans.add((ent.start_char, ent.end_char))
                        found.append(self._ent(val, "PERSON", ent.start_char, ent.end_char, "spacy"))
                elif ent.label_ in ("GPE", "LOC"):
                    val2 = ent.text.strip()
                    if len(val2) < 3 or _is_non_person(val2):
                        continue
                    key = (ent.start_char, ent.end_char)
                    if key not in seen:
                        seen.add(key)
                        found.append(self._ent(val2, "LOCATION", ent.start_char, ent.end_char, "spacy"))

        # ── D. ALL-CAPS names — single AND multi-word ─────────────────────────
        # Single word ALL-CAPS Indian names (HARSHITHA, BAVYASHREE, LAKSHANYA)
        for m in re.finditer(r'\b([A-Z]{4,25})\b', text):
            val = m.group(1)
            # Skip known abbreviations
            if val in _CAPS_SKIP:
                continue
            # Skip if non-person word
            if val.lower() in NON_PERSON_WORDS:
                continue
            # Accept if it's a known Indian name
            if _is_known_indian_name(val):
                key = (m.start(), m.end())
                if key not in seen:
                    seen.add(key)
                    found.append(self._ent(val, "PERSON", m.start(), m.end(), "caps-known"))
                continue
            # For unknown ALL-CAPS words, only accept if 6+ chars (likely a name, not acronym)
            if len(val) >= 7:
                key = (m.start(), m.end())
                if key not in seen:
                    seen.add(key)
                    found.append(self._ent(val, "PERSON", m.start(), m.end(), "caps-long"))

        # Multi-word ALL-CAPS names (ROSY JOHNSON, ARJUN KUMAR)
        for m in _CAPS_NAME.finditer(text):
            val   = m.group(1).strip()
            words = val.split()
            if len(words) < 2:
                continue
            if _is_caps_abbreviation(val):
                continue
            if any(len(w) <= 2 for w in words):
                continue
            if _is_non_person(val):
                continue
            if not all(w.isalpha() for w in words):
                continue
            key = (m.start(1), m.end(1))
            if key not in seen:
                seen.add(key)
                found.append(self._ent(val, "PERSON", m.start(1), m.end(1), "caps-multi"))

        # ── E. Title-case names ───────────────────────────────────────────────
        for m in _TITLE_NAME.finditer(text):
            val = m.group().strip()
            words = [
                w for w in val.split()
                if w.rstrip(".") not in ("Dr","Mr","Mrs","Ms","Prof","Sri","Smt","Shri")
            ]
            if len(words) < 2:
                # Single title-case word — only if known Indian name
                if len(words) == 1 and _is_known_indian_name(words[0]):
                    key = (m.start(), m.end())
                    if key not in seen:
                        seen.add(key)
                        found.append(self._ent(val, "PERSON", m.start(), m.end(), "title-known"))
                continue
            if _is_non_person(val):
                continue
            if not _looks_like_name(" ".join(words)):
                continue
            key = (m.start(), m.end())
            if key not in seen:
                seen.add(key)
                found.append(self._ent(val, "PERSON", m.start(), m.end(), "title"))

        # ── F. Lowercase known Indian names (harshi, harshu, bavyashree) ──────
        for m in _LOWER_NAME.finditer(text):
            val = m.group(1)
            if _is_known_indian_name(val) and val.lower() not in NON_PERSON_WORDS:
                key = (m.start(), m.end())
                if key not in seen:
                    seen.add(key)
                    found.append(self._ent(val, "PERSON", m.start(), m.end(), "known-lower"))

        # ── Sort & remove overlapping spans ──────────────────────────────────
        found.sort(key=lambda e: e["start"])
        clean, last = [], -1
        for e in found:
            if e["start"] >= last:
                clean.append(e)
                last = e["end"]
        return clean

    @staticmethod
    def _ent(text, label, start, end, source):
        return {"text": text, "label": label, "start": start, "end": end, "source": source}

    def redact(self, text: str, level: int = 1, extra: list = None) -> tuple:
        entities = self.detect_entities(text)

        # User-supplied custom words
        if extra:
            taken = {(e["start"], e["end"]) for e in entities}
            for word in extra:
                for m in re.finditer(re.escape(word), text, re.IGNORECASE):
                    key = (m.start(), m.end())
                    if key not in taken:
                        entities.append(self._ent(m.group(), "CUSTOM", m.start(), m.end(), "user"))
            entities.sort(key=lambda e: e["start"])
            clean, last = [], -1
            for e in entities:
                if e["start"] >= last:
                    clean.append(e)
                    last = e["end"]
            entities = clean

        counters = {}
        lmap     = {}
        result   = []
        prev     = 0
        stats    = {"total": 0, "by_type": {}}

        for ent in entities:
            result.append(text[prev:ent["start"]])
            orig  = ent["text"]
            label = ent["label"]
            key   = (label, orig.upper())

            if level == 1:
                rep = _mask(orig)

            elif level == 2:
                if key not in lmap:
                    counters[label] = counters.get(label, 0) + 1
                    prefix = _LABELS.get(label, label.title())
                    lmap[key] = f"{prefix} {counters[label]}"
                rep = lmap[key]

            else:   # level 3
                if key not in lmap:
                    gen = _FAKE.get(label, _fn)
                    lmap[key] = gen()
                rep = lmap[key]

            result.append(rep)
            prev = ent["end"]
            stats["total"] += 1
            stats["by_type"][label] = stats["by_type"].get(label, 0) + 1

        result.append(text[prev:])
        return "".join(result), stats