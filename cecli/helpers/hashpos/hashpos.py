import re

import xxhash

# Delimiter used to wrap public hash IDs
HASH_DELIMITER = "—"
UNIQUE_HASH_DELIMITER = "——"


class HashPos:
    # 1024-character Base1024 corpus
    B1024 = (
        "0123456789ABCDEFGHIJ"
        "KLMNOPQRSTUVWXYZabcd"
        "efghijklmnopqrstuvwx"
        "yz¡£§©«®°±·»¿×ßæðøĐđ"
        "ıłœəαβγδεηθικλμνοπρς"
        "στυφχωАБВГДЕЗИКЛМНОП"
        "РСТУФЦЧЭЯабвгдежзикл"
        "мнопрстуфхцчшщъыьэюя"
        "іאבדהוחילמנערשת،ابةت"
        "ثجحخدذرزسشصضطظعغفقكل"
        "منهوىيپکگیकतनपमरलसहন"
        "রกขคงจชณดตถทนบปผพมยร"
        "ลวสหอะาเแใไ‐–—―‘’“”„"
        "†•′※€←→−─│█■●★☆♥♪、。《"
        "》「」『』【】〜あいうえおかきくけこさし"
        "すせそたちっつてとなにのはまみめもやよら"
        "りるれろわをんアィイウェエオカキクコサシ"
        "スセタチッテトナニフマムメャュョラリルレ"
        "ロン・ー一万三上下不与专业东两个中为主么"
        "义之也书了事二于五些交产享京人亿今介从他"
        "付代以们件价任份企会传但位体何余作你使例"
        "供価保信修倍值停像元先入全公共关其具内円"
        "册再写出击分列则初利别到制前力功加务动動"
        "包化北区十午华单南即历原去县参及友反发取"
        "变口只可台右号司合同名后向否含听启告员周"
        "命和品哈商問器四回因国图土在地场型城基報"
        "場增声处备复外多大天失头女好如始子字存学"
        "安完定实客家容密对导将小少尔就局展山岁州"
        "工左已市布常平年并广序库应店度建开式引张"
        "当录形影径待後得微心必志态思性总息您情意"
        "感成我或户所手打技投报拉持指按换据排接推"
        "提播支收改放政效数整文料断新方族无日时明"
        "易星是時景更最月有服期木未本机权束条来板"
        "构果查标样格案模次款止正此步歳段每比民気"
        "水求江没治法注活流海消清游源火点無然片版"
        "物特率环现球理生用由电男画界番登的目直相"
        "省看県真知码确示社票私种科秒称移程税空立"
        "站章端笑符第等简算管米类系素索约级线组经"
        "结给统编网置美老考者而联能自至色节英藏行"
        "表装西要見见规视角解言計記話読计认议记论"
        "设证评试话该语误说请读调象责败货费资起超"
        "路身车转载辑输达过运近还这进连述退送选通"
        "速造連道部都配释里重量金错长開間関门闭问"
        "间队阳陆限院除雅集雷需非面音页项题首验高"
        "黑가간개거게결경고공과구그글기나내는능니"
        "다당대도동되된드든들디라래러력로록료류른"
        "를름리만메면명목문미버번보복부분비사산상"
        "색생서성세션소수스습시식신아야어에여열오"
        "와요용우운원위으은을음의이인일임입자작장"
        "재적전정제져조주지진째체출치크태터턴트하"
        "한할함해호화환회�ª²³´µ¹º¼½ÀÁ"
        "ÂÃÄÇ"
    )

    _B1024_REGEX_SET = "".join(re.escape(c) for c in B1024)

    # Regex matches EITHER the exact string '——' OR a tilde-wrapped 4-character Base1024 hash
    HASH_PREFIX_RE = re.compile(
        rf"^({UNIQUE_HASH_DELIMITER}|{HASH_DELIMITER}[{_B1024_REGEX_SET}]{{4}}{HASH_DELIMITER})"
    )
    FRAGMENT_RE = re.compile(
        rf"^({UNIQUE_HASH_DELIMITER}|{HASH_DELIMITER}[{_B1024_REGEX_SET}]{{4}}{HASH_DELIMITER})$"
    )

    # Loose prefix for robust stripping: Matches a emdash-wrapped 8-char string containing non-ASCII
    _LOOSE_PREFIX_RE = re.compile(rf"^[{HASH_DELIMITER}]?\S{{0,8}}{HASH_DELIMITER}")

    def __init__(self, source_text: str = ""):
        self.lines = source_text.splitlines()
        self.total = len(self.lines)

        self.line_counts = {}
        for line in self.lines:
            if line.strip():
                self.line_counts[line] = self.line_counts.get(line, 0) + 1

    def _get_line_hash(self, text: str) -> int:
        return xxhash.xxh3_64_intdigest(text.encode("utf-8")) & 0xFFFFF

    def generate_public_id(self, text: str, line_idx: int, occurrence: int) -> str:
        line_hash = self._get_line_hash(text)

        # Explicit modulo for bounds wrapping
        idx_bits = line_idx % 16384
        occ_bits = occurrence % 64

        packed = (line_hash << 20) | (idx_bits << 6) | occ_bits

        res = ""
        for i in range(3, -1, -1):
            res += self.B1024[(packed >> (10 * i)) & 0x3FF]
        return res

    def unpack_public_id(self, public_id: str) -> tuple[int, int, int]:
        packed = 0
        for i, char in enumerate(public_id):
            packed |= self.B1024.index(char) << (10 * (3 - i))

        occ_bits = packed & 0x3F
        idx_bits = (packed >> 6) & 0x3FFF
        line_hash = (packed >> 20) & 0xFFFFF

        return line_hash, idx_bits, occ_bits

    def format_content(self, start_line: int = 1) -> str:
        formatted_lines = []
        seen = {}

        for i, line in enumerate(self.lines):
            if not line.strip():
                formatted_lines.append(f"{line}")
                continue

            count = self.line_counts[line]

            if count == 1:
                # Flush directly against code using the unique token
                formatted_lines.append(f"{UNIQUE_HASH_DELIMITER}{line}")
            else:
                occ = seen.get(line, 0) + 1
                seen[line] = occ
                prefix = self.generate_public_id(line, i, occ)
                # Wrap the generated Base1024 hash in tildes
                formatted_lines.append(f"{self.get_wrapped_id(prefix)}{line}")

        return "\n".join(formatted_lines)

    def resolve_to_lines(self, public_id: str, start_line: int = 1) -> list[int]:
        if public_id == UNIQUE_HASH_DELIMITER:
            raise ValueError(
                f"Cannot spatially resolve the unique '{UNIQUE_HASH_DELIMITER}' identifier without line text."
            )

        # Strip the surrounding tildes to unpack the core 4 characters
        clean_id = public_id.strip(HASH_DELIMITER)
        if len(clean_id) != 4:
            raise ValueError(f"Invalid public ID string for unpacking: {public_id}")

        target_line_hash, target_idx, target_occ = self.unpack_public_id(clean_id)

        matches = []
        for i, line in enumerate(self.lines):
            if self._get_line_hash(line) == target_line_hash:
                matches.append((i, line))

        if not matches:
            return []

        if len(matches) == 1:
            return [matches[0][0]]

        current_seen = {}
        scored_matches = []

        for i, line in matches:
            current_seen[line] = current_seen.get(line, 0) + 1
            current_occ = current_seen[line]

            # Apply identical modulo to current spatial data before comparing
            current_idx_mod = i % 16384
            current_occ_mod = current_occ % 64

            # Cartesian distance squared
            distance_sq = ((current_idx_mod - target_idx) ** 2) + (
                (current_occ_mod - target_occ) ** 2
            )
            scored_matches.append((distance_sq, i))

        scored_matches.sort(key=lambda x: x[0])
        return [m[1] for m in scored_matches]

    def resolve_range(self, start_id: str, end_id: str) -> tuple[int, int]:
        starts = self.resolve_to_lines(start_id)
        ends = self.resolve_to_lines(end_id)

        if not starts or not ends:
            raise ValueError(f"Could not resolve IDs: {start_id}..{end_id}")

        for s in starts:
            for e in ends:
                if s <= e:
                    return s, e

        raise ValueError(
            f"Found matches for {start_id} and {end_id}, but no logically ordered range."
        )

    @staticmethod
    def get_wrapped_id(public_id: str) -> str:
        """Wrap a public ID with the HashPos delimiters for use in hashline content."""
        return f"{HASH_DELIMITER}{public_id}{HASH_DELIMITER}"

    @staticmethod
    def strip_prefix(text: str) -> str:
        if text is None:
            return ""
        lines = text.splitlines(keepends=True)
        result_lines = []
        for line in lines:
            stripped_line = HashPos.HASH_PREFIX_RE.sub("", line, count=1)
            if stripped_line == line:
                stripped_line = HashPos._LOOSE_PREFIX_RE.sub("", line, count=1)
            result_lines.append(stripped_line)
        return "".join(result_lines)

    @staticmethod
    def extract_prefix(line: str) -> str:
        match = HashPos.HASH_PREFIX_RE.match(line)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def normalize(hashpos_str: str, throw=True) -> str:
        if hashpos_str is None:
            raise ValueError("HashPos string cannot be None")

        match = HashPos.HASH_PREFIX_RE.match(hashpos_str)
        if match:
            return match.group(1)

        if throw:
            raise ValueError(f"Invalid HashPos format '{hashpos_str}'.")
        else:
            return False
