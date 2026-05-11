# Relevance Rubric v1

Rate each (query, document) pair on a 0–3 scale based on how well the document satisfies the user's intent expressed by the query.

**3 — Highly relevant.** This document is exactly what the user wants. They would click through, find the information / product they're looking for, and consider the search successful. Examples: searching "wireless noise-canceling headphones" and getting Sony WH-1000XM5; searching "running shoes for flat feet" and getting a model explicitly designed for flat feet.

**2 — Relevant.** This document substantially addresses the query but isn't the perfect match. The user would consider it useful but might keep looking. Examples: searching "wireless noise-canceling headphones" and getting wireless headphones without active noise cancellation; searching "running shoes for flat feet" and getting general running shoes that don't specifically address flat feet.

**1 — Marginally related.** This document is in the same general category as the query but doesn't address the user's specific intent. The user would skip it. Examples: searching "wireless noise-canceling headphones" and getting wired earbuds; searching "running shoes for flat feet" and getting hiking boots.

**0 — Irrelevant.** This document has nothing meaningful to do with the query. Examples: searching "wireless noise-canceling headphones" and getting a kitchen appliance; searching "running shoes for flat feet" and getting a book about feet anatomy.

When in doubt between two ratings, choose the lower one — relevance ratings should be conservative.
