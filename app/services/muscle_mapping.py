# ================= 2. Definisi glossary gym muscle ke body part =================

muscle_to_body_part = {
    "sternocleidomastoid": "neck",
    "splenius capitis": "neck",
    "splenius cervicis": "neck",
    "front deltoids": "shoulders",
    "side deltoids": "shoulders",
    "rear deltoids": "shoulders",
    "upper chest": "chest",
    "middle chest": "chest",
    "lower chest": "chest",
    "upper traps": "back",
    "lower traps": "back",
    "rotator cuff": "back",
    "teres major": "back",
    "lats": "back",
    "erector spinae": "back",
    "rectus abdominis": "abs",
    "obliques": "abs",
    "serratus": "abs",
    "biceps brachii": "biceps",
    "brachialis": "biceps",
    "long head": "triceps",
    "lateral head": "triceps",
    "medial head": "triceps",
    "brachioradialis": "forearms",
    "flexors": "forearms",
    "extensors": "forearms",
    "gluteus maximus": "glutes",
    "gluteus medius": "glutes",
    "gluteus minimus": "glutes",
    "rectus femoris": "quadriceps",
    "vastus lateralis": "quadriceps",
    "vastus medialis": "quadriceps",
    "vastus intermedius": "quadriceps",
    "biceps femoris": "hamstrings",
    "semitendinosus": "hamstrings",
    "semimembranosus": "hamstrings",
    "gastrocnemius": "calves",
    "soleus": "calves",
    "cardio": "cardio",
}

def map_injury_to_body_parts(injuries: list[str]) -> list[str]:
    """
    Map list of injured muscle names to body parts using muscle_to_body_part dictionary.
    Jika otot tidak ditemukan mapping-nya, diasumsikan string injury adalah body part langsung.
    """
    body_parts = set()
    for injury in injuries:
        injury_lower = injury.lower()
        if injury_lower in muscle_to_body_part:
            body_parts.add(muscle_to_body_part[injury_lower])
        else:
            # Asumsi kalau injury bukan otot tapi body part langsung
            body_parts.add(injury_lower)
    return list(body_parts)