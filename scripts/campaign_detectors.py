import re

UNSURE_MARKERS = (
    "not sure", "unsure", "cannot remember", "can't remember", "do not remember",
    "don't remember", "does not remember", "doesn't remember", "cannot recall",
    "can't recall", "no idea", "do not know", "don't know", "does not know",
    "doesn't know", "forgotten", "forgets", "vague about", "hazy", "not certain",
)
SUBJECT_TOKENS = r"\b(you're|your|you|they're|their|they|he|she|the agent|the receptionist|the clinic)\b"
CALLER_SUBJECTS = ("you", "your", "you're")
CLINIC_OWNED_HINTS = (
    "they", "their", "the clinic", "accept", "covered", "coverage", "open", "hours",
    "policy", "in network", "available", "went through", "stuck", "booked", "on file",
    "on record", "in the system", "confirmed",
)
CALLER_OWNED_HINTS = ("your", "you ", "which day", "what day", "when you", "your own")
REFUSAL_MARKERS = (
    "refuse", "refusing", "decline", "declining", "withhold", "withholding",
    "will not give", "won't give", "do not give", "don't give", "will not say",
    "won't say", "do not say", "don't say", "not willing to give", "unwilling to give",
    "reluctant to give", "reluctant to share", "avoid giving", "resist giving",
    "hold back", "rather not give", "rather not say", "push back on giving",
    "does not want to give", "doesn't want to give", "not want to give",
    "keep to yourself", "keeps to yourself",
)
IDENTIFICATION_TARGETS = (
    "name", "date of birth", "dob", "identify", "identification", "profile", "who you are",
)
PROFILE_WORDS = ("profile", "account")
PROFILE_CREATION_VERBS = (
    "set up", "sets up", "setting up", "create", "creates", "creating",
    "register", "registering", "sign up", "signing up", "start one", "set one up",
)
RECORD_WORDS = ("record", "profile", "account", "chart", "in their system", "in the system")
RECORD_EXISTS_MARKERS = (
    "already", "exists", "existing", "on file", "on record", "from last time",
    "from before", "they have your", "you are registered", "previously set up",
)
NEGATION_MARKERS = (" not ", "n't", "never", "no record", "no profile", "yet to")
PROFILE_EXISTS_MARKERS = (
    "already", "exists", "existing", "on file", "on record", "from last time",
    "from before", "have a profile", "has a profile", "confirm",
)

def stonewalls_identification(persona_text):
    for sentence in re.split(r"[.;!?\n]", persona_text.lower()):
        if not any(target in sentence for target in IDENTIFICATION_TARGETS):
            continue
        for marker in REFUSAL_MARKERS:
            if marker in sentence:
                return sentence.strip(), marker
    return None, None


def asserts_a_record(persona_text):
    for sentence in re.split(r"[.;!?\n]", persona_text.lower()):
        if any(marker in sentence for marker in NEGATION_MARKERS):
            continue
        if not any(word in sentence for word in RECORD_WORDS):
            continue
        for marker in RECORD_EXISTS_MARKERS:
            if marker in sentence:
                return sentence.strip(), marker
    return None, None


def _last_subject_before(text):
    found = None
    for match in re.finditer(SUBJECT_TOKENS, text):
        found = match.group(1)
    return found


def unsure_of_own_life(persona_text):
    for sentence in re.split(r"[.;!?\n]", persona_text.lower()):
        for marker in UNSURE_MARKERS:
            index = sentence.find(marker)
            if index < 0:
                continue
            if _last_subject_before(sentence[:index]) not in CALLER_SUBJECTS:
                continue
            rest = sentence[index + len(marker):]
            if any(hint in rest for hint in CLINIC_OWNED_HINTS):
                continue
            if any(hint in rest for hint in CALLER_OWNED_HINTS):
                return sentence.strip(), marker
    return None, None


def creates_a_profile(persona_text):
    for sentence in re.split(r"[.;!?\n]", persona_text.lower()):
        if not any(word in sentence for word in PROFILE_WORDS):
            continue
        if any(marker in sentence for marker in PROFILE_EXISTS_MARKERS):
            continue
        for verb in PROFILE_CREATION_VERBS:
            if verb in sentence:
                return sentence.strip(), verb
    return None, None
