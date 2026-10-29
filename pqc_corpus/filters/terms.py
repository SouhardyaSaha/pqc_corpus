"""PQC terms the commit filters use to decide whether a commit mentions PQC.

The scheme names are 74 names of a reference list of PQC schemes plus 25 further
names found while reviewing commits by hand (as of 2026-10-09). A filter that
removes commits keeps any commit matching one of these, so a missing name could
remove real PQC work; `tests/test_terms.py` checks that every listed name matches.

Matching rules:
- Ordinary names match case-insensitively, with or without separators
  (`ML-KEM`, `ml_kem`, `mlkem`, `ML KEM`) and with a parameter-set suffix
  (`mlkem768`, `sntrup761`), not preceded by a letter (`ntru` does not match
  inside "untrusted", but `X25519MLKEM768` matches).
- Names that are also ordinary English or code words (CROSS, LESS, Wave, HAWK,
  Falcon...) match only in their exact published spelling as a whole word, or
  with a parameter set (`falcon-512`, `bikel3`, `mayo_2`), so they do not fire on
  every "less" or "cross" in code.
- Generic PQC terms (post-quantum, liboqs, PQClean, FIPS 203...) always match.

These terms are wider than the 90 collection terms of `config/corpus_policy.json`:
they decide what the filter keeps, not what was collected.
"""

import re

# The reference list, then the names found by hand review.
SCHEME_NAMES = (
    "ML-KEM", "Kyber", "ML-DSA", "Dilithium", "Falcon", "FN-DSA", "SLH-DSA", "SPHINCS+", "XMSS",
    "NTRU", "Classic McEliece", "FrodoKEM", "HQC", "BIKE", "LMS", "HSS", "Rainbow", "SABER",
    "NTRU Prime", "MAYO", "X-Wing", "SIKE", "UOV", "HAWK", "SIDH", "qTESLA", "SNOVA", "MQOM",
    "QC-MDPC", "SQIsign", "MQDSS", "Round5", "AIMer", "GeMSS", "ROLLO", "Three Bears", "FAEST",
    "HAETAE", "KINDI", "LEDAcrypt", "LEDAkem", "LUOV", "QR-UOV", "RQC", "RYDE", "SDitH",
    "Ascon-Sign", "BIG QUAKE", "HuFu", "MiRitH", "NTS-KEM", "SQUIRRELS", "TUOV", "3WISE", "ALTEQ",
    "DME-Sign", "EagleSign", "FuLeeca", "HILA5", "KAZ-SIGN", "Mirath", "Preon", "eMLE-Sig",
    "pqsigRM",
    # Found by hand review, not on the reference list.
    "Aigis-Enc", "Aigis-Sig", "BAT", "Biscuit", "CROSS", "EHT", "Gravity-SPHINCS", "HPPC", "LESS",
    "LIMA", "MEDS", "MIRA", "McEliece", "NewHope", "PERK", "PROV", "PRUNE-HORST", "Picnic",
    "Raccoon", "SPHINCS-Alpha", "Titanium", "VOX", "WOTS+", "Wave", "Xifrat1-Sign",
)

# Names that are also common words; matched only in their exact spelling (or with
# a parameter set, below), as a whole word.
AMBIGUOUS = frozenset({
    "AIMer", "BAT", "BIKE", "Biscuit", "CROSS", "EHT", "Falcon", "HAWK", "HSS", "HuFu", "KINDI",
    "LESS", "LIMA", "LMS", "MAYO", "MEDS", "MIRA", "PERK", "Picnic", "Preon", "PROV", "Raccoon",
    "Rainbow", "ROLLO", "RQC", "RYDE", "SABER", "SQUIRRELS", "Titanium", "VOX", "Wave",
})

# Spellings of ambiguous names that are unambiguous in code (parameter sets, variants).
AMBIGUOUS_VARIANTS = (
    r"falcon[-_]?(?:512|1024|padded)",
    r"hawk[-_]?(?:256|512|1024)",
    r"mayo[-_]?[1-5]",
    r"bike[-_]?l?[135]",
    r"(?:light|fire)?saber[-_]?kem",
    r"lightsaber|firesaber",
    r"rainbow[-_]?(?:i|iii|v)[-_]?(?:classic|circumzenithal|compressed)",
    r"picnic[-_]?(?:l[135]|[23]|full|fs|ur)",
    r"lms[-_](?:sha256|shake256)",
    r"hss[-_](?:sha256|shake256)",
)

# Other spellings and lineage names for unambiguous schemes.
ALIASES = (
    "sntrup", "ntrulpr", "mceliece", "frodo", "xwing", "threebears", "wots", "aigis", "xifrat",
    "crystals-kyber", "crystals-dilithium", "sphincsplus", "sphincs",
)

# Terms that are about PQC in general, not one scheme.
GENERIC = (
    r"post[-_ ]?quantum", r"quantum[-_ ](?:safe|resistant|secure|proof)", r"pqc\w*", r"liboqs\w*",
    r"oqs\w*", r"pqclean\w*", r"pq[-_]?crypto\w*", r"fips[-_ ]?20[3456]",
)

# Repository names, descriptions and topics may also use these broader words.
REPOSITORY_ONLY = (r"quantum\w*", r"lattice\w*", r"pq\b")


def _flexible(name: str) -> str:
    """Case-insensitive pattern: separators optional, `+` optional, parameter suffix allowed."""
    base = re.sub(r"[-_/ ]?(?:unspecified)$", "", name)
    parts = re.findall(r"[A-Za-z0-9]+", base.replace("+", " plus "))
    parts = [p for p in parts if p.lower() != "plus"]
    joined = r"[-_ ]?".join(re.escape(p) for p in parts)
    return joined + r"(?:\+|[-_]?plus)?\w*"


def _scheme_patterns() -> tuple[str, str]:
    """(case-insensitive pattern, case-sensitive pattern) for all scheme names."""
    loose = [_flexible(n) for n in SCHEME_NAMES if n not in AMBIGUOUS]
    loose += [_flexible(a) for a in ALIASES] + list(AMBIGUOUS_VARIANTS)
    exact = [re.escape(n) for n in sorted(AMBIGUOUS, key=len, reverse=True)]
    return "|".join(loose), "|".join(exact)


_LOOSE, _EXACT = _scheme_patterns()
# A digit may precede a scheme name, as in hybrid names like X25519MLKEM768.
SCHEME_LOOSE = re.compile(rf"(?<![A-Za-z])(?:{_LOOSE})", re.IGNORECASE)
SCHEME_EXACT = re.compile(rf"(?<![A-Za-z0-9])(?:{_EXACT})(?![A-Za-z0-9])")
GENERIC_TERMS = re.compile(rf"(?<![A-Za-z0-9])(?:{'|'.join(GENERIC)})", re.IGNORECASE)
REPOSITORY_TERMS = re.compile(rf"(?<![A-Za-z0-9])(?:{'|'.join(REPOSITORY_ONLY)})", re.IGNORECASE)


def mentions_pqc(text: str) -> bool:
    """True if the text names a PQC scheme or uses a generic PQC term."""
    return bool(SCHEME_LOOSE.search(text) or SCHEME_EXACT.search(text) or GENERIC_TERMS.search(text))


def pqc_named_repository(name: str, description: str, topics: list[str]) -> bool:
    """A repository whose name, description or topics are about PQC (broader words allowed)."""
    text = " ".join([name, description, *topics])
    return mentions_pqc(text) or bool(REPOSITORY_TERMS.search(text))
