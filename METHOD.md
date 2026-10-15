# How this ledger works

**DRAFT — Nova to tidy, Makho to approve before it goes live.** This page is rendered at `/ledger/method/`. The rules below are the Page Spec's rules in plain language.

## What the ledger is

A public, dated, scored record of VectorSpace Infrastructure's forecasts about the data center market. It exists so that someone with capital at stake can check our judgment without taking anyone's word for it. Every call is written by the author, in the author's words, and frozen on the day it is published.

## What counts as a call

A call is a specific, falsifiable statement about the data center market with a number or an event, a geography, a fixed resolution date, and a resolution rule that names in advance the source and method that will decide it. A trend, a vibe, or a claim that cannot be judged by a stranger on a set date is not a call and is not on this page.

## How a call is timestamped

Each call is one file in a public repository. The commit that adds the file is the publication: the commit date is the call's date, and the commit is signed by the author's account. After the page is published it is saved to the Internet Archive's Wayback Machine, and the archived copy is linked from the call. The build that produces this site refuses to publish if any frozen field of a published call has changed since its first commit. A correction is a new call that names the one it supersedes; the original stays and resolves on its own terms.

## Statuses

- **Open.** Published and waiting. Indicator checks are logged under the call.
- **Flagged.** An indicator or an event has moved against the call. We flag within 14 days of noticing. The claim and the confidence do not change.
- **Resolved YES / NO.** Set on, or within 14 days after, the resolution date, by applying the resolution rule to the named source. The resolving page is archived and linked.
- **Void.** The named source no longer exists, or the claim proved ambiguous as written. Voids are listed and counted, never deleted. If more than 10% of calls are void, the page says so.
- **Retracted.** Withdrawn by the author before resolution. A retraction scores as a miss at the stated confidence, so it is a miss declared early, not a free exit.

## How calls are scored

Each call carries a stated probability that it resolves YES, in 5-point steps. A resolved call contributes a Brier score of (p − o)², where p is the stated probability and o is 1 for YES and 0 for NO. Lower is better; 0.25 is what a coin flip earns. The page shows the mean Brier score and the number of calls behind it. The hit rate counts a call as a hit when it was made at 50% or more and resolved YES, or made under 50% and resolved NO. Once twenty calls have resolved, a calibration table (what we said versus what happened, by confidence level) joins the headline numbers.

## What a call page shows

The claim; the dates, confidence and status; the commit and archive links; what the consensus view was when the call was made, with sources; the resolution rule; the leading indicators we watch and their latest readings; what evidence would change our mind; who the call matters to and which of our services it relates to; the log of updates; and, once resolved, what happened and a short postmortem.

## Prior calls

Calls the author made before this ledger existed are listed separately, with the dated public post that made each one. They are scored on their own and never pooled with this page, because the selection process was different: this page records every call made; the prior page records the ones the author could document after the fact.
