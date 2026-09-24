"""Quality lab: large-scale, multi-domain evaluation of question generation,
follow-up behaviour, grading and cost across model combinations.

The lab drives the real HTTP API in-process, simulates learners whose ability is
known in advance, asks an independent judge model to rate the output blindly and
aggregates quality against cost.
"""
