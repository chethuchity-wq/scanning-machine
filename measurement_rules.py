"""
Suggest which report blank each unlabelled scan value belongs to.

When the sonographer measures with the plain distance calliper, the scanner
sends only "Dist 9.70 cm" - no organ. These rules guess the organ from what
the scanner does send for each image, in the order the images were taken:

  - how the values are grouped on one image (one value, a pair, three, a
    volume) and their sizes, and
  - the routine order of an abdomen-pelvis scan: liver, (gall bladder),
    right kidney, (spleen), left kidney, bladder, uterus, endometrium,
    ovaries.

They are *suggestions*: the dashboard shows each next to its image and the
doctor fills it in with a click. Size alone can't always tell organs apart
(a gall bladder can measure like a kidney), so nothing is filled silently.
Ranges are in cm and generous, for adults and children.
"""

from __future__ import annotations

from itertools import permutations

# Report fields, with the label of their row in the abdomen-pelvis forms and
# which blank in that row they fill (the dashboard finds them by label)
FIELDS = {
    "liver_size": ("Liver", 1),
    "spleen_size": ("Spleen", 1),
    "right_kidney_size": ("Right kidney", 1),
    "left_kidney_size": ("Left kidney", 1),
    "uterus_size": ("Uterus", 1),
    "endometrium_mm": ("Uterus", 2),
    "right_ovary_size": ("Right ovary", 1),
    "right_ovary_volume": ("Right ovary", 2),
    "left_ovary_size": ("Left ovary", 1),
    "left_ovary_volume": ("Left ovary", 2),
    "prostate_size": ("Prostate", 1),
    "prostate_volume": ("Prostate", 2),
}

LIVER = (10.0, 20.0)                       # span / length
SPLEEN = (6.0, 14.5)
SPLEEN_WITH_KIDNEY = (8.5, 14.5)   # spleen measured in the same view as the left kidney
KIDNEY_LENGTH, KIDNEY_WIDTH = (6.5, 13.5), (2.8, 6.8)
UTERUS_LONGEST = (4.5, 12.0)
ENDOMETRIUM = (0.2, 2.2)
OVARY = (1.0, 5.5)
OVARY_MIN_VOLUME_ML = 1.0
BLADDER_VOLUME_ML = 80
PROSTATE_VOLUME_ML = (8, 80)


class Size(float):
    """A length in cm that remembers how the scanner printed it ("4.20")."""
    text: str

    def __new__(cls, value: float, text: str):
        obj = super().__new__(cls, value)
        obj.text = text
        return obj


def _num(v: dict) -> float | None:
    try:
        return float(v["value"])
    except (KeyError, TypeError, ValueError):
        return None


def _within(x: float, rng: tuple[float, float]) -> bool:
    return rng[0] <= x <= rng[1]


def _fmt(*values: float) -> str:
    return " x ".join(getattr(v, "text", f"{v:g}") for v in values)


def _kidney_pair(a: float, b: float) -> bool:
    length, width = max(a, b), min(a, b)
    return _within(length, KIDNEY_LENGTH) and _within(width, KIDNEY_WIDTH) and length / width >= 1.5


def _image_groups(images: list[dict]):
    """(image file, preset, lengths in cm, volume in ml or None) per measured image."""
    seen = set()
    for img in images:
        lengths, volume = [], None
        for v in img.get("values", []):
            x = _num(v)
            if x is None:
                continue
            unit = v.get("unit", "").lower()
            if unit in ("ml", "cc"):
                volume = x
            elif unit == "cm":
                lengths.append(Size(x, str(v["value"])))
            elif unit == "mm":
                lengths.append(Size(x / 10, f"{x / 10:g}"))
        if not lengths and volume is None:
            continue
        # The same measurement saved twice (two images) counts once
        key = (tuple(lengths), volume)
        if key in seen:
            continue
        seen.add(key)
        yield img["file"], img.get("preset", ""), lengths, volume


def suggest(images: list[dict], scan_type: str) -> list[dict]:
    """
    Suggestions for an abdomen-pelvis or follicular report, in report order:
    [{"field", "label", "blank", "value", "unit", "image", "why"}].
    Other report types get none (their values come labelled from the scanner).
    """
    male = scan_type == "abdomen_pelvis_male"
    if not (scan_type.startswith("abdomen_pelvis") or scan_type == "follicular_study"):
        return []

    found: dict[str, dict] = {}
    kidneys: list[dict] = []
    ovaries: list[dict] = []
    uterus_seen = False

    def add(field, value, unit, image, why):
        if field not in found:
            label, blank = FIELDS[field]
            found[field] = {"field": field, "label": label, "blank": blank,
                            "value": value, "unit": unit, "image": image, "why": why}

    for image, preset, lengths, volume in _image_groups(images):
        n = len(lengths)
        pelvic = preset.startswith("GYN")

        # Volume measurements: bladder, prostate or ovary
        if volume is not None:
            if volume >= BLADDER_VOLUME_ML:
                continue  # urinary bladder - the forms print no bladder size
            if male and _within(volume, PROSTATE_VOLUME_ML) and n == 3:
                add("prostate_size", _fmt(*lengths), "cm", image, f"3 sizes with volume {volume:g} ml")
                add("prostate_volume", f"{volume:g}", "ml", image, "volume shown on the scan")
            # Under 1 ml is a small lesion measured in the uterus, not an ovary
            elif (not male and n >= 2 and volume >= OVARY_MIN_VOLUME_ML
                  and all(_within(x, OVARY) or x < 1.0 for x in lengths)):
                ovaries.append({"value": _fmt(*lengths), "image": image, "why": f"small volume {volume:g} ml",
                                "volume": f"{volume:g}"})
            continue

        if n == 1:
            x = lengths[0]
            if "liver_size" not in found and not kidneys and not pelvic and _within(x, LIVER):
                add("liver_size", _fmt(x), "cm", image, "first single long measurement")
            elif kidneys and not pelvic and not uterus_seen and _within(x, SPLEEN):
                add("spleen_size", _fmt(x), "cm", image, "single measurement after a kidney")
            elif uterus_seen and _within(x, ENDOMETRIUM):
                add("endometrium_mm", f"{x * 10:g}", "mm", image, "thin measurement after the uterus")
            continue

        if n == 2:
            a, b = lengths
            if not pelvic and _kidney_pair(a, b):
                kidneys.append({"value": _fmt(max(a, b), min(a, b)), "image": image, "spleen": False,
                                "why": "length x width of kidney size"})
            elif uterus_seen or pelvic:
                if all(_within(x, OVARY) for x in (a, b)):
                    ovaries.append({"value": _fmt(a, b), "image": image, "why": "two small sizes in the pelvis"})
            continue

        # Three or four values on one image
        # Kidney pair + spleen length (left kidney and spleen in one view)
        if n == 3 and not pelvic:
            combo = next(((a, b, c) for a, b, c in permutations(lengths)
                          if a > b and _kidney_pair(a, b) and _within(c, SPLEEN_WITH_KIDNEY) and c > a), None)
            if combo:
                a, b, c = combo
                kidneys.append({"value": _fmt(a, b), "image": image, "spleen": True,
                                "why": "kidney measured with the spleen"})
                add("spleen_size", _fmt(c), "cm", image, "measured with the left kidney")
                continue
        # Two ovaries side by side: two small pairs
        if n == 4 and uterus_seen and all(_within(x, OVARY) for x in lengths):
            ovaries.append({"value": _fmt(*lengths[:2]), "image": image, "why": "first pair of small sizes"})
            ovaries.append({"value": _fmt(*lengths[2:]), "image": image, "why": "second pair of small sizes"})
            continue
        if male and n == 3 and "prostate_size" not in found and all(_within(x, (1.5, 7.0)) for x in lengths):
            add("prostate_size", _fmt(*lengths), "cm", image, "three sizes in the pelvis")
            add("prostate_volume", f"{lengths[0] * lengths[1] * lengths[2] / 2:.1f}", "ml", image,
                "calculated: sizes multiplied, divided by 2")
            continue
        # Uterus: three sizes (a fourth small one is the endometrium)
        if not male and not uterus_seen:
            sizes, extra = lengths[:3], lengths[3:]
            if _within(max(sizes), UTERUS_LONGEST) and min(sizes) >= 1.5:
                uterus_seen = True
                add("uterus_size", _fmt(*sizes), "cm", image, "three sizes in the pelvis")
                if extra and _within(extra[0], ENDOMETRIUM):
                    add("endometrium_mm", f"{extra[0] * 10:g}", "mm", image, "fourth, thin size with the uterus")

    # Kidneys: the one measured with the spleen is the left; otherwise the
    # routine is right first, then left
    if kidneys:
        with_spleen = [k for k in kidneys if k["spleen"]]
        left = with_spleen[0] if with_spleen else (kidneys[1] if len(kidneys) > 1 else None)
        right = next((k for k in kidneys if k is not left), None)
        if right:
            add("right_kidney_size", right["value"], "cm", right["image"], right["why"] + ", measured first")
        if left:
            add("left_kidney_size", left["value"], "cm", left["image"], left["why"])
    for side, ovary, order in zip(("right", "left"), ovaries, ("first", "second")):
        add(f"{side}_ovary_size", ovary["value"], "cm", ovary["image"], f"{ovary['why']}, {order}")
        if ovary.get("volume"):
            add(f"{side}_ovary_volume", ovary["volume"], "ml", ovary["image"], "volume shown on the scan")

    order = list(FIELDS)
    return sorted(found.values(), key=lambda s: order.index(s["field"]))
