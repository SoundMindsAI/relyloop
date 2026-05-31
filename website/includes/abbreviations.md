*[Bayesian optimization]: A search strategy that builds a probabilistic model of which parameter values tend to score well, then concentrates each new trial where improvement is most likely — far more efficient than trying every combination.
*[TPE]: Tree-structured Parzen Estimator — the Bayesian sampling algorithm Optuna uses by default to pick each trial's parameters.
*[Optuna]: The open-source optimization framework RelyLoop uses to run and coordinate trials.
*[nDCG]: Normalized Discounted Cumulative Gain — a ranking-quality metric that rewards placing the most relevant results near the top.
*[ERR]: Expected Reciprocal Rank — a ranking metric that models how likely a user is to stop once they hit a relevant result.
*[LTR]: Learning to Rank — machine-learned models that re-order search results. RelyLoop tunes their query-time parameters but does not train the models in v1.
*[UBI]: User Behavior Insights — a standardized schema of search queries and click/interaction events, used to derive relevance judgments from real usage.
*[SRW]: Search Relevance Workbench — OpenSearch's native relevance-tuning tool.
*[DCO]: Developer Certificate of Origin — a lightweight per-commit sign-off (used instead of a CLA) certifying you have the right to contribute your code.
*[query set]: A named collection of the search queries you want to optimize relevance for.
*[judgment list]: A set of per-query, per-document relevance ratings the loop scores search results against.
*[search space]: The set of query-time parameters the loop is allowed to vary, together with their permitted ranges.
