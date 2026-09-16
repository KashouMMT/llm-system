"""
Every instruction this plugin sends to a vision or reasoning model.

The same split the other plugins follow: a `plugin_prompt.txt` beside a
plugin's `__init__.py` is text injected into the *system* prompt and paid
for on every turn, and a `prompts.py` holds what the plugin says only
when it actually runs. Recycling deliberately has no `plugin_prompt.txt`
— it exposes no tools, only `/recycle` slash commands, which never reach
the agent at all, so there is nothing the model needs to be told in
advance.

It sits inside `pipeline/` rather than at the plugin root, unlike the
other plugins' prompts.py, for one concrete reason: the pipeline package
is imported by `commands.py`, which is imported by the plugin's
`__init__.py`. A module under `pipeline/` importing from the plugin root
would re-enter that partially-initialised package and fail. Keeping the
prompts beside the code that sends them also keeps `pipeline/` the
self-contained unit it was written as.

`{labels}` and `{targets}` are str.format placeholders filled by the
caller.
"""

# --------------------------------------------------------------------------
# Detection (vision.py)
# --------------------------------------------------------------------------

# One image, no target list: the product path for a single photograph.
OPEN_SCAN = """\
List every distinct physical object visible in this image.

Rules:
- Use simple lowercase singular common nouns ("laptop", not "Dell XPS 13 laptop").
- Group identical objects into ONE entry with a count. Six identical chairs is
  one entry with count 6, not six entries.
- Group objects of the same kind even if they differ in colour or size.
- Do NOT identify brands or models. A 2K TV and a 4K TV are both "tv".
- Do NOT assess condition or damage.
- Include structural parts of the room (door, wall, window, floor, ceiling) if
  you see them. The caller filters those out; that is not your job.
- If you are unsure what something is, still list it with your best guess and a
  low confidence rather than omitting it.
"""

# One image plus a closed list: used to re-check specific labels, where an
# absence has to come back as count 0 rather than as a missing row.
TARGETED = """\
Count how many of each of these objects are visible in this image:

{targets}

Rules:
- Return exactly one entry per object in the list above, in that order.
- Use the object name exactly as written above as the label.
- If an object is not present, return it with count 0.
- Do NOT report anything that is not on the list.
"""

# Several images of ONE room in a single call. The "count it ONCE" rule is
# the whole reason this prompt exists rather than looping OPEN_SCAN per
# photo: per-photo counts are not additive, and summing them double-counts
# every object visible from two angles.
MULTI_VIEW = """\
The images that follow are multiple photographs of ONE room, taken from
different positions or angles. They are views of the same physical space, not
separate rooms.

List every distinct physical object visible across all of the images
combined, with a total count for each.

Rules:
- If the same physical object appears in more than one photo (e.g. a sofa
  visible in image 1 and again in image 2 from another angle), count it
  ONCE, not once per photo. Do NOT count the same physical object twice.
- Use simple lowercase singular common nouns ("laptop", not "Dell XPS 13
  laptop").
- Group identical objects into ONE entry with a count. Six identical chairs
  is one entry with count 6, not six entries.
- Group objects of the same kind even if they differ in colour or size.
- Do NOT identify brands or models. A 2K TV and a 4K TV are both "tv".
- Do NOT assess condition or damage.
- Include structural parts of the room (door, wall, window, floor, ceiling)
  if you see them. The caller filters those out; that is not your job.
- If you are unsure what something is, still list it with your best guess
  and a low confidence rather than omitting it.
"""


# --------------------------------------------------------------------------
# Catalog build (build.py)
# --------------------------------------------------------------------------

# Stage 2. The "every input label must appear exactly once" rule is the
# plugin's one standing rule stated as a prompt: nothing detected may
# disappear before a human has seen it.
CLUSTER = """\
Below is every object label a vision model produced across a set of photographs,
with how many times each appeared. Group them into canonical items.

Merge two labels ONLY if they name the same physical object AND would be handled
identically. "table" and "desk" merge. "headset" and "headphone" merge.
"mouse" and "mouse pad" do NOT merge - they are different objects that happen to
have similar names. "office chair" and "plastic chair" do NOT merge - same
category, different objects.

Mark `excluded` for anything that is not a collectable item:
- structure of the building: wall, floor, ceiling, window, door, curtain
- people and clothing
- food, drink, and rubbish
- surfaces and fixtures that stay with the room

Every input label must appear exactly once, either as a canonical_label or in
exactly one aliases list. Do not drop any, and do not invent labels that are not
in the input.

Observed labels:
{labels}
"""

# Stage 3. The price ban is deliberate and load-bearing: an LLM knows
# physical facts about kinds of object and does not know markets, so a
# plausible wrong price is worse than the null a human can fill in.
ENRICH = """\
For each item below, give typical physical properties of ONE unit, as commonly
found in a household or small warehouse.

Rules:
- Estimate from general knowledge. These are approximations and are labelled as
  such downstream, so a reasonable estimate is far better than null.
- Use null only when the item is so variable that any number would mislead.
- Dimensions are the bounding box in centimetres, largest dimension first.
- Give a min and max weight that honestly reflect how much this varies.
- Do NOT estimate price. Price is not your job and a plausible wrong price is
  worse than no price.

Items:
{labels}
"""
