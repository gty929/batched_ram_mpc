# Skill: Writing Clear Systems and Security Research Papers

Use this skill when drafting, revising, or reviewing a systems, security,
cryptography-systems, or performance-oriented research paper.

The guide is ordered from the largest unit to the smallest:

- Part 1 sets the goals and the priority order that resolves conflicts.
- Parts 2 and 3 cover the structure of the paper and of each section.
- Parts 4, 5, and 6 cover paragraphs, sentences, and words.
- Part 7 covers specific kinds of content: security claims, prior work,
  numbers, evaluation, figures, and tables.
- Part 8 describes how to draft, revise, and review.
- Part 9 is the final self-check.

A project may keep a separate notes file (for example,
`PAPER_WRITING_NOTES.md`) with the author's decisions, verified facts, and
conventions for one paper. The notes override this guide for that paper.
When a review produces a new lesson, merge a general lesson into the
matching section here and a paper-specific decision into the notes file.
Do not append lessons as a separate list.

## Recurring problems

A ★ after a heading marks a rule that earlier drafts broke repeatedly. These
rules were added several times from separate reviews before the guide was
consolidated. Give them extra weight, and check them first:

- **Define before use** (§6.4, §4.5). Every term, problem, picture, and
  justification must rest on what the reader has already been given.
- **Link the sentences** (§4.3, §4.4). Each sentence follows visibly from the
  previous one, and causes and problems come before results and remedies.
- **Say it once** (§2.4, §4.6). Do not restate a mechanism, a caveat, or the
  previous sentence.
- **Explain reasons, not mechanics** (§2.1, §3.5, §3.6, §7.5). Keep the main
  text at the level of ideas, teach the clean construction, and do not
  narrate figures.
- **Think with the reader** (§3.9, §1.3). Raise each difficulty before its
  mechanism, so the design reads as the resolution of a problem the reader
  has felt, not as a reference solution.
- **Readability over defensiveness** (§1.4, §8.4). Do not add qualifications
  or hedges to a true sentence. An unsupported claim gets an author note.
- **Sound written, not generated** (§5.3, §5.9, §8.2). Avoid semicolon and
  em-dash chains, generic transitions, corrective contrasts, and telegraphic
  stubs.
- **Credit and compare precisely** (§3.3, §7.2.6, §7.2.10). Credit the
  framework to its originator, describe a shared technique once, and keep the
  prior-work baseline in view.
- **Keep the science when revising** (§8.3). Shortening or polishing never
  removes a comparison, number, or insight without accounting for it.

## The running example

Most examples come from a paper on oblivious RAM (ORAM) inside trusted
execution environments (TEEs). The paper accelerates ORAM with AVX-512
vector instructions. The following background is enough to follow the
examples:

- An *ORAM* hides which records a program accesses. A *hierarchical ORAM*,
  introduced by Goldreich and Ostrovsky, stores records in a sequence of hash
  tables of increasing size, called *levels*. Every access probes one bucket
  in every level, and a found record is written back into the smallest level,
  the *online stash*. Small levels fill up and are periodically *rebuilt* into
  larger ones. A rebuild must be *oblivious*: its memory addresses must not
  reveal where any record goes.
- *H2O2RAM* is the closest prior system. Its implementation rebuilds the hash
  tables with *bitonic sort*, an oblivious sort that makes
  \(\Theta(\log^2 n)\) passes over \(n\) records.
- A *butterfly network* moves each record to its destination bucket in a
  sequence of *stages*. Each stage is made of *merge-splits*, which take two
  buckets and split their records by one bit of the destination. Prior
  oblivious sorts built on the network use buckets of at least 512 records.
- The paper's main observation is that a 512-bit register holds 64 bytes.
  With 64-record buckets stored *byte-sliced* (one 64-byte line holds the same
  byte of every record), a merge-split becomes a few register permutations.
  Permuting a register involves no memory address, so it reveals nothing.
- Small buckets overflow, so the paper gives each network stage a *stash*
  for overflowing records (*residuals*). The *branching factor* \(B\) is the
  size ratio between consecutive levels. *Deamortization* runs rebuilds in the
  background so that requests never pause. A *tombstone* records an erasure,
  or a lookup of an absent key (a *miss*).
- `\sys` is the macro for the system's name.

Examples that use specific section numbers or reviewer requests show the kind
of mistake to avoid. They are not rules about that paper.

---

# Part 1. Goals and Priorities

## 1.1 What the paper must convey

A technically competent reviewer, including one outside the exact subfield,
should understand on one pass:

1. what problem the paper addresses;
2. what is new;
3. why the new design works;
4. why it is faster, cheaper, or otherwise better than prior work;
5. what security or correctness properties are preserved; and
6. what evidence supports the claims.

Every section, paragraph, sentence, notation choice, citation, figure, and
appendix reference should serve one of these purposes. Grammatical prose is
not the goal.

## 1.2 Priority order

When rules conflict, use this order:

1. **Technical correctness**
2. **A clear, consequential main idea**
3. **Low reader effort**
4. **Evidence and consistent quantities**
5. **Precision appropriate to the claim**
6. **Stylistic polish**

"Technical correctness" means that a sentence is true under the reading a
competent reader would naturally give it. It does not mean that the sentence
survives every adversarial reading, names every edge case, or uses accounting
vocabulary. Rank 1 justifies fixing a false sentence. It never justifies
making a true, readable sentence harder to read (§1.4).

Completeness is not a goal in itself. Simplify aggressively without making a
claim false. State the assumptions needed to understand the result, and move
derivations, exceptions, and secondary variants to supporting material. Never
improve the prose by weakening the scientific point.

The reader-engagement techniques in this guide (motivation, pacing, emphasis)
build on correctness, consistent notation, clear paragraph purpose, precise
quantities, and supported claims. They never excuse violating those. An
engaging example must still match the figure, and a memorable conclusion must
keep its assumptions and baseline.

## 1.3 Write for a reader who can stop

Assume readers skim, forget notation, and will not reconstruct an argument
from scattered details. The contribution should come through from the topic
sentences, figures, and comparison tables before the reader studies any
derivation. Understanding why the result matters must not require patience
or familiarity with the implementation.

An AI reader can be told to process every definition and reconstruct every
connection. A human reader first decides whether a passage deserves that
effort. When technical content looks unmotivated, the usual reaction is to
skip it, not to infer patiently why it is there. Correctness and eventual
comprehensibility are therefore not enough. Before asking the reader to absorb
notation, an assumption, or a mechanism, make clear what question it answers
and what understanding it will buy.

When ordering material, imagine how an expert and a non-expert each react to
every paragraph: what each already cares about, where each would lose
interest, and what would keep each reading.

## 1.4 Readability over defensiveness ★

A research paper conveys ideas to researchers. It is not a specification, a
user manual, or a legal document. Readers bring ordinary common sense and read
each claim at the depth of its location. Do not write for a reader hunting for
loopholes.

Rewrite a sentence for precision only when a competent reader would actually
reach a different, wrong conclusion from it. "Could someone misread this?" is
the wrong test. "Would a typical reader of this section misread this?" is the
right one.

Keep a short, readable sentence over a longer, complete one. When the precise
version needs two extra clauses, put the extra precision in the next sentence
or in supporting material, or drop it if the argument does not use it.
Readers misunderstand a sentence that tries to say everything more often than
one that says the main point clearly.

---

# Part 2. Paper-Level Structure

## 2.1 Put each piece of information at the right depth ★

Each tier of the paper carries a different kind of content:

| Tier | Carries |
|---|---|
| Abstract, introduction preamble | Each component and its benefit, not how it works |
| Main text | The idea, its cause, and the strongest useful result |
| Appendix and supporting material | Exact accounting, proofs, full derivations, detailed algorithms, complete schedules, extended measurements, secondary optimizations, implementation exceptions |
| Author notes (rendered) | Open editorial or technical questions for the author |
| Source comments (LaTeX `%`) | Records for later revisions that ask nothing of the author, such as a verified discrepancy between a prior paper and its code that the text deliberately leaves out |

Moving a detail out of the main text can improve rigor, because the central
claim and its assumptions become easier to find.

At the shallowest depth, "An access then finds the record's tree position
with one OMAP lookup" is construction detail that an abstract does not need.
"We apply similar byte-sliced techniques to the tree-based ORAM and use our
small-entry OMAP as its position map, which further reduces memory overhead"
gives the component and what it buys. Vague phrasing such as "reorganize the
tables to limit their additional storage cost" is acceptable at this depth,
as long as every word is one the reader already knows (§6.4).

When a result concerns sufficiently large inputs, give its leading term. Keep
lower-order corrections only when they change the conclusion in the regime
being discussed. Do not introduce symbols only to express cases the reader
does not yet need.

## 2.2 Lead with what the reader cares about

Headline numbers are the cheapest reason to keep reading. A speedup, a
latency, or a memory ratio against a named baseline needs almost no context,
and a reader who has just seen it wants to learn how it was achieved. Open a
contributions list with what the system offers and its headline results,
leaving marked blanks until the measurements exist, and then present the
techniques. Do not save the numbers for a closing "Implementation and
evaluation" paragraph.

Order the techniques by how much they matter to the reader. A secondary fix,
such as hiding repeated misses on absent keys, should not come first merely
because it concerns the basic operations.

## 2.3 Spend space in proportion to importance

The bottleneck path, such as the online access, deserves the most space and a
figure. A secondary mechanism, such as how rebuild threads are scheduled,
needs a sentence or two. A paper that reads like documentation of the
implementation loses the reader. The main text does not need to specify the
scheme completely. A deliberately vague description is fine as long as the
high-level idea is clear and nothing it says is false.

## 2.4 Give each fact one home ★

Definitions, mechanisms, caveats, derivations, and lists (contributions,
baselines, threat-model assumptions, design goals) each have one
authoritative location. Elsewhere, refer to it. Duplicates drift.

- **Mechanisms.** Explain each mechanism once.
- **Results.** If the main text states a bound and the appendix derives it,
  the appendix derives that same result rather than restating and
  reinterpreting it. Do not keep two copies of equations, parameter sets,
  assumption lists, or baseline lists.
- **Qualifications.** State each caveat once, where it governs. A model
  assumption belongs in the caption of the table that reports model numbers,
  or in the section that defines the model. An exceptional case, such as
  backpressure under overload, belongs in the section that describes that
  mechanism, not in the abstract or a contribution statement. Do not repeat
  "model result" or "under the stated assumptions" in every sentence that uses
  a number. A reader who sees a caveat five times assumes the authors doubt
  their own result.

The exception is a result against prior work. Repeat the baseline wherever the
result appears (§7.2.10), so that a reviewer reading one paragraph does not
have to hunt for what was beaten.

## 2.5 The appendix fulfills promises

The appendix supplies what the main text promised. It does not rerun the main
text. Begin an appendix subsection with at most one orientation sentence, then
give the material. Do not re-explain the motivation, the prior-work
limitation, or the high-level mechanism unless the supplementary material
cannot be understood without it.

## 2.6 Cross-references are promises

If the main text says "Appendix B gives the value of \(c\)," then Appendix B
must contain the value of \(c\). After revising a section, revisit every
reference that points to it. A forward reference that no longer lands on what
it promises is a correctness problem.

The promise includes its framing. If one section says that a later one "hides
repeated lookups of an absent key, unlike H2O2RAM," the later section must name
H2O2RAM and say how it leaks, not only describe the new mechanism. Cite the
same source for the same fact in both places.

Do not hide behind a reference what one sentence can state now. When a choice
comes up, state it there: "We leave the copy in place and discuss the reasons
in Section X." Writing only "Section X explains our choice" leaves the reader
holding an open question and makes the paper feel mysterious. The
justification can wait for the section that has the needed mechanisms. Defer
the reasons, not the decision.

---

# Part 3. Section-Level Structure

## 3.1 One purpose and one topic per section

Before drafting, complete this sentence:

> This section needs to convince the reader that ______.

If the blank cannot be filled clearly, the section is not ready to draft.

A reader who cannot say what a subsection is about stops reading it
carefully. Its title and first paragraph should name one topic, and every
paragraph should serve it. When two subsections overlap, regroup the material
by topic instead of adding cross-references between them. For example, if one
subsection explains where two tables meet during a merge and the next explains
it again for overflow handling, the topics are mixed.

Place each optimization with the thing it optimizes. Routing groups of buckets
through several stages in cache concerns the traversal of the whole network,
not the single merge-split kernel, so it belongs where the paper discusses the
rebuild's memory traffic.

## 3.2 Openings and headings

A section can start directly with its first subsection. It does not need a
preamble that summarizes the whole argument. An orientation sentence is
useful when it states the question the coming passage answers. It is filler
when it only announces that an explanation is coming ("We now describe ...").

A preview in a section opening may mention only what the reader can already
understand. Defer the rest to the subsection that explains it.

Headings:

- **Name the object.** In "Adapting the Construction to Fast Merge-splits,"
  "the construction" could be the merge-split itself. "Bottlenecks after Fast
  Merge-splits" names what the subsection is about.
- **Keep a subsection title on one line.**
- **Define the heading's term.** A paragraph titled "Read-only hash tables"
  that says only "we leave older copies in place" has not said what
  "read-only" means. Add the link: "so accesses write only to the online
  stash, and a hash table never changes after it is built."
- **Use a topic that reads naturally.** Not every paragraph needs a heading.
- **Make paragraph headings parallel noun phrases.** Within a subsection,
  name each paragraph's object in the same form and with the paper's own
  terms ("Throughput without batching," "Throughput with batching"). Avoid
  clause fragments ("What the optimizations buy"), prepositional stubs
  ("Against SONIC"), and two paragraphs headed by the same bare word
  ("Batches"). A subsection that interprets results can simply be titled
  "Discussion of the Results"; do not invent a title from two of its
  topics.
- **Do not lean on the previous heading's text.** A paragraph that opens a
  heading must not start with "this" or "thus" pointing back across it.

## 3.3 Explain the framework before changing it ★

Do not assume the reader knows the framework the paper modifies. If the
contribution changes how a hierarchical ORAM, a tree ORAM, or a consensus
protocol works, first describe that framework as the closest prior system
instantiates it: its structure, the procedure the paper changes, the
invariant that must survive, and the cost the paper attacks. Then describe the
new design by its differences from that baseline. A reader who does not know
how the baseline rebuilds its tables cannot see why a faster rebuild matters.

Background covers only **definition → relevant invariant → operation needed
later**. Do not turn it into a literature tutorial unless the paper depends on
that history. End it with the specific efficiency gap the section addresses.

Do not open with a claim about a whole class of constructions when it holds
for only one instantiation. "Hierarchical ORAM repeatedly rebuilds its hash
tables" is false for hierarchies built from other structures. Name the
instantiation.

Credit a framework to the work that introduced it, and present later systems
as instantiations. If the levels, dummy probes, and rebuild schedule come from
Goldreich and Ostrovsky, do not write "we follow H2O2RAM." Cite the original
construction, say that practical instantiations such as H2O2RAM use the same
ideas, and credit the later system only with what it changed (§7.2.5).

## 3.4 Choose an argument shape

Use the structure that matches the section's purpose rather than one template
everywhere.

### Mechanism

**need → security or correctness constraint → prior approach → its cost → our
idea → saving**

### Systems or scheduling optimization

**naive execution → bottleneck → exploitable workload property → new
schedule → saving → deferred work**

Say whether work is eliminated, reduced, moved off the critical path, or done
asynchronously but still paid eventually.

### Revisiting a known technique

**what the technique does for our problem → how it works → prior uses and
their results → their concrete limitation → its cause → our observation that
removes the cause → the new problem this creates → our fix, crediting borrowed
ideas**

For example: a bucket hash table can be rebuilt by routing records directly
through a butterfly network; the network's prior uses are oblivious sorts,
whose measured gains over bitonic sort are small; one cause is that large
buckets make every merge-split an oblivious network of depth at least
\(\log Z\); with 64-record buckets a merge-split becomes a few register
permutations; small buckets overflow often; per-stage stashes adapted from
prior work absorb the overflow.

Open with the technique's role in the paper's own problem, not with the
problem another literature used it for. Cite prior uses from a different
problem, such as sorting, where the text discusses their limitations. Explain
how the technique works before stating a limitation that depends on its
internals: "each merge-split needs a network of depth \(\log Z\)" means
nothing to a reader who has not seen what a merge-split does.

### Design choice

**alternatives → actual tradeoff → property of our setting → chosen design**

Do not describe every design rejected during development.

- **Present a split convention as a choice.** Whether a hierarchical-ORAM
  lookup marks the entry it finds is a choice on which the literature splits.
  Cite schemes on both sides, then give the reasons for ours. Otherwise the
  reader assumes the baseline's convention is the only option and wonders why
  ours deviates.
- **Do not present a prior choice as new.** Cite the schemes that made it, and
  spend the words on why it matters in our setting. A well-known choice is
  still worth explaining when it enables the paper's own mechanism.
- **Lead with a shared requirement.** When one requirement motivates several
  choices, state it first: "Rebuilding in the background leads to two
  choices: tables that accesses never modify, and rebuilds that merge two
  tables at a time." For each choice, give the intuition for how it serves the
  requirement. A background merge that reads read-only tables works on a fixed
  snapshot and never races with accesses.
- **Give every consequential advantage.** Small buckets make each merge-split
  a few register permutations. They also let a rebuild load a group of buckets
  into cache and route it through several stages before writing it back.
  Credit the prior work each advantage borrows from.
- **Rank the advantages.** Say which one decided the choice, give it first,
  and mark the rest as secondary: "The main reason is that read-only tables
  keep background rebuilding simple. ... Leaving older copies in place also
  makes writes cheap." "First, ... Second, ..." tells the reader the reasons
  weigh the same. Use it only when they do.
- **Make each advantage concrete.** Say what the alternative would have to do,
  not only that ours is "simpler": if accesses marked copies in tables that a
  rebuild reads, "every mark made during the rebuild would have to be logged
  and replayed on the rebuilt table." Then state the gain as speed or security
  against a named baseline: writes that skip the table probes, or repeated
  misses that H2O2RAM leaks and we hide.
- **Show an equivalence briefly.** When two designs do the same work and
  differ only in organization, such as rebuilding all levels in one step
  versus merging two tables at a time, show the equivalence in one sentence
  and a figure. Spend the paragraph on what our organization buys. Name the
  prior systems on each side, after checking how each one actually works.
- **End on the transition.** Order the remaining reasons so that the last one
  leads into the next paragraph.

### Consequences of a core technique

When the main technique changes the cost balance of the surrounding system,
collect its follow-on changes in one place, one consequence at a time:

**what becomes cheap → what we rebalance; what becomes the bottleneck → how
we relieve it; what new problem appears → how we solve it**

For example, byte-sliced merge-splits make rebuilds cheap relative to lookups
(so we raise the branching factor), leave memory traffic as the rebuild's
bottleneck (so we route groups of buckets in cache), and make small buckets
overflow often (so we add stashes). The reader then sees one argument rather
than a list of unrelated optimizations.

Open with one paragraph that names the problems the technique leaves or
creates, with enough cause for each that the reader accepts it. Then give each
problem its own paragraph that starts from the remedy ("To reduce a rebuild's
memory traffic, ..."), without restating the problem.

When a consequence is a deliberate trade, say so. "We therefore deliberately
make rebuilds do more work so that each lookup probes fewer tables" leaves no
doubt that the extra work is a choice, not an accident.

### Evaluation result

**claim → intuition → measurement setup → representative results →
explanation** (§7.4)

## 3.5 The main text explains reasons; mechanics go elsewhere ★

The main text explains **why** the design has its structure. For each
mechanism, emphasize:

1. the problem it solves;
2. the property that makes the problem difficult;
3. the key idea;
4. why the idea is correct or secure;
5. where the saving comes from.

Include enough mechanism to make the causal argument followable, but do not
simulate an algorithm listing in prose. Details that do not affect the
reasoning belong in an algorithm, an implementation section, or the appendix.

- **Data layouts.** When the paper introduces a layout, say in a sentence or
  two how the system's basic operation uses it before turning to the operation
  it was designed for. A byte-sliced bucket built for merge-splits also serves
  every lookup, and a reader who sees only the merge-split wonders how a lookup
  reads a record spread across 64-byte lines. Describe the use once, next to
  the layout. Open the layout's paragraph with the cost it avoids (for
  example, gathering one byte from each of 64 records) before defining it.
- **Kernels with special instructions.** The reader needs the cost, not the
  instruction sequence. Give the cost without the feature (an instruction
  count), the feature and what it does, the cost with it, and the measured
  speedup. How a fallback computes its result goes in a source comment. An
  input class handled differently with a consequence for correctness does
  belong in the text: keys longer than 8 bytes are compared as hashes in
  pieces and can produce a false match, so they get a short paragraph with the
  bound.
- **Complex mechanisms.** For a mechanism with many parts, such as overflow
  handling with per-stage stashes, range partitioning, and a final sweep, walk
  the reader through one figure at a high level: what goes wrong; the idea and
  whom it borrows from; what happens to the data; why the result is correct
  and oblivious. Describe the steps only when the steps themselves are the
  idea, and even then give each step's purpose and leave what is visible
  (sizes, colors, positions) to the figure. Proofs, capacity bounds, traversal
  orders, and buffer management go in the appendix.

## 3.6 Teach one clean construction first ★

Use the simplest faithful description. Teach one construction with a
representative configuration first, and introduce generalizations,
configuration choices, and boundary cases afterward. Storage ownership and
naming conventions belong in the main argument only when they change the
algorithm, the security, or a resource bound. An implementation choice does
not by itself invalidate an equivalent abstract description.

Distinguish a simplifying assumption made for exposition from a design
decision or a correctness requirement, and say which it is when it appears.
"We first use a uniform branching factor \(B\)" leaves the reader asking why.
"For simplicity, we first assume the same branching factor \(B\) at every
level" tells the reader to expect the general case later. Make sure the paper
then relaxes the assumption. Do not explain why an obviously simpler choice is
simpler, or justify every assumption. That extra explanation defeats the
simplification.

## 3.7 Introduce the main observation slowly

The main observation deserves the most careful pacing in the paper. Do not
compress it into one paragraph of consequences, and do not preview it before
the reader has the facts it rests on. This preview

> Our buckets hold 64 records, so one AVX-512 register holds the same byte of
> every record in a bucket. Merging and splitting two buckets then takes two
> permutation instructions per byte position, and each stage becomes a single
> pass over the table.

packs four ideas into three sentences, and none can be checked yet. Build the
observation one step per sentence, each resting on the previous one: the
obstacle (a merge-split must hide where each record goes, and a memory address
would reveal it); the insight (permuting a register involves no address); the
enabling fact (a 512-bit register holds 64 bytes, one per record); the
resulting choice (64-slot buckets, stored byte-sliced); and only then the
mechanism and its cost. The payoff, such as 20 passes instead of 325, comes
after the reader has followed the chain.

Open with what the paper does. If prior work uses the same tool
differently, fold the contrast into that first sentence ("X can do more
than ...") rather than interrupting the chain with it. State a design
choice right after the fact that forces it, before the mechanism that uses
it.

## 3.8 Pace the section and reward the reader's effort

After a derivation, a run of definitions, or a subtle mechanism, give the
reader a payoff before the next substantial burden:

- a conclusion that answers the question motivating the passage;
- a concrete outcome, saving, or comparison with a meaningful baseline;
- a short insight that makes a puzzling design choice clear;
- a diagram that reveals the structure at a glance.

For example, after explaining arena reuse, conclude that the completed table
becomes the outgoing carry without a relocation copy. That outcome tells the
reader what the storage schedule accomplished.

A reward adds understanding. It does not announce "this is important" or
repeat the preceding sentences. Let a conclusion stand briefly before burying
it under qualifications and new symbols. Vary the pace with the argument
rather than imposing a quota of conclusions or figures.

An example is not automatically a reward. Several named regions, routing bits,
versions, and exceptional cases can make an example harder than the rule it
explains, and numerical specificity alone does not make anything intuitive.
Choose the smallest example that exposes the key relationship. Reuse existing
notation and figure labels, say what the reader should notice, and stop once
that point is visible. If the example needs a new glossary or a long
simulation of the algorithm, simplify it, draw it, move it to supporting
material, or omit it. An intricate example that is necessary evidence is
demanding material and needs its own motivation.

## 3.9 Think with the reader ★

A text that only states the design reads like a reference solution: correct,
complete, and cold. Readers engage when they see the difficulty before the
answer, so that the design arrives as the resolution of a problem they have
already started to think about. Write each design passage as a short line of
reasoning that the reader follows with you. This builds on §1.3 (motivate
before asking for effort) and §3.8 (reward the effort).

**Make the content itself interesting first.** Most of the effect comes from
structure and pace, not from wording:

- **Order the material so that each step answers a problem the previous
  step created.** Two costs named at the end of one paragraph become the
  topics of the next two. A reader who knows what is still unsolved reads on
  to find out how it is solved.
- **Raise the difficulty before the mechanism**, preferably as a concrete
  moment: "The access that completes a carry for the top waits while the
  merge rebuilds a table of \(N\) records." A paragraph that opens with
  "Each level reserves an arena of three regions" asks the reader to accept a
  layout before they know why anyone would want it.
- **Find the fact that is surprising, and place it where the expectation has
  been set.** A required rebuild speed of \(4.5\times\) looks high. Most of it
  comes from the branching factor, and deamortization adds only \(3\%\). That
  is a payoff only if the reader sees the \(4.5\times\) first.
- **Pace the passage.** Alternate burden and payoff (§3.8), end a subsection
  on a result rather than on a mechanism detail, and cut flat material that
  neither raises nor resolves anything.
- **Use "we" for the reasoning, not only for the system.** "We cannot simply
  reserve less storage, because a level without space stalls the whole
  rebuild pipeline" invites the reader into the tradeoff. "\sys reserves ..."
  only reports the outcome.
- **Do not turn a roadmap into a list of answers.** "Pre-routing reduces the
  extra probes, and the arena of Section 3.2 reduces the extra storage" gives
  answers to problems the reader has not felt yet, under names the reader has
  not learned yet. State the costs plainly, and let the following paragraphs
  take them up one at a time.

**Then use wording to mark the turns, sparingly.** A few phrases tell the
reader where the reasoning turns:

- "at first glance, ...", "it seems ..., but ...", "... turns out to be
  ...", and "the remaining question (or cost) is ..." mark an expectation and
  its resolution, or the transition to what is still open;
- a purpose clause placed first ("To keep accesses from waiting for merges,
  ...") tells the reader why before what;
- a natural first thought followed by the observation that breaks it ("a
  merge seems unable to start before its carry arrives, but most of its work
  never touches the carry") is the case that §5.9 allows, because the
  rejected idea is one the reader actually holds.

These phrases are shortcuts. Use only a few in a section, never two in one
paragraph, and never the same one twice. A turn phrase on content that is not
actually surprising reads as forced. Rhetorical questions are rarely needed,
because a stated difficulty does the same work. Use at most one or two in a
section, each answered at once, and never a question that only announces a
topic ("What about storage?"), which is a label (§5.1).

Keep the register of a research paper. Do not use exclamation marks, "let's,"
instructions to the reader, colloquial phrases ("the price is paid
elsewhere," "put to work"), or suspense for its own sake. Engagement never
excuses an imprecise claim (§1.2). The twist must be true. A warmer sentence
is easy to overstate, so check each new claim it makes.

---

# Part 4. Paragraph Level

## 4.1 One point, stated first

Each paragraph makes one main point, normally in its first sentence. The rest
supports, explains, quantifies, qualifies, or derives it. The reader should
not have to reach the end to learn why the paragraph exists. If a paragraph
needs two unrelated topic sentences, split it.

Test: read only the first sentence of every paragraph in a section. They
should form a coherent argument.

## 4.2 Every sentence has a job

A technically correct sentence is not automatically useful. Each sentence
should do one of these: state a problem or claim, explain a cause or a
consequence, describe mechanism the argument needs, introduce an assumption,
compare with prior work, give evidence, define a term, or connect one stage of
the argument to the next.

Delete sentences that restate nearby text or narrate the writing process.

## 4.3 Make each sentence follow from the previous one ★

At each sentence boundary, ask what relation the reader should infer. If the
answer is "the next fact on the same topic," the paragraph is a list: either a
link is missing, or the sentence belongs elsewhere.

A paragraph of short declaratives that each start a new subject reads as
robotic even when every sentence is correct:

> A key longer than 8 bytes does not fit in one lane. \sys therefore stores
> such a key as its 16-byte hash under a secret key, and a merge compares the
> hashes in four 4-byte pieces. A record counts as a duplicate when each piece
> of its hash equals the piece at the same position of some hash in the other
> bucket. The four pieces may come from different hashes, so a record can be
> dropped by mistake. Because the hashes are secret and random, each piece
> matches by chance with probability at most \(64 \cdot 2^{-32}\) ...

The last sentence answers the risk raised by the one before it, but nothing
says so. Link each sentence to its predecessor with a connective or a pointing
phrase, and mark a concession as one:

> A key longer than 8 bytes does not fit in one lane, so \sys stores it as its
> 16-byte hash under a secret key and compares the hashes in four 4-byte
> pieces. A merge then drops a record when every piece of its hash matches the
> same piece of some hash in the other bucket. The four matches may come from
> different hashes, in which case the record is dropped by mistake.
> Nonetheless, because the hashes are secret and random, ...

Useful links: *because, therefore, so, then, which allows, which requires, as
a result, whereas, while, but, nonetheless* (a concession: the risk just
stated is real, but small), and pointing phrases such as "in which case" or
"such a mistake."

A section opening that lists consequences without causes has the same
problem:

> Byte-sliced merge-splits change the costs that the rest of the construction
> must balance. Rebuilding becomes cheap relative to lookups, memory traffic
> rather than computation limits the speed of a rebuild, and the small buckets
> overflow routinely.

Give each consequence its cause and the response it calls for:

> Byte-sliced merge-splits make rebuilding cheap relative to lookups, so we
> spend more rebuild work to make each lookup probe fewer tables. Because
> merge-splits need so little computation, memory traffic now limits the
> speed of a rebuild ...

## 4.4 Put causes, conditions, and problems first ★

Do not ask readers to infer why a result occurs. The order within a paragraph
is cause before consequence, condition before effect, and problem before
remedy.

- **Cause before result.** "Our method reduces the rebuild time by 3.2×" is
  weak. "Prior work sorts each level independently. We instead perform one
  global sort and route the resulting records to all levels. This removes
  \(L-1\) sorts and reduces rebuild time by 3.2×" makes the number meaningful.
- **Condition before effect.** A draft said that "each merge of a cascade
  continues the network where the previous one stopped," and only two
  sentences later that "continuing the network requires every merge of a
  cascade to use the routing hash of the final table." State the condition
  first: every merge routes records by the final table's hash, so the merges
  form one butterfly network and each merge runs the next stages of it.
- **Problem before remedy.** After "Large rebuilds can therefore cause long
  pauses," the sentence "Deamortization spreads rebuilding over successive
  accesses" opens with a new term and leaves the reader to guess how it
  relates to the pauses. Lead with the connection: "To avoid these pauses,
  deamortization rebuilds the tables gradually while requests continue."
- **Problem before the mechanism that handles it.** "The network brings
  duplicate keys together along the way" is confusing if nothing earlier
  explains why a rebuild sees duplicate keys. First establish the problem
  (lookups leave older copies in larger levels because published tables are
  immutable), then the mechanism.
- **Shared task before a prior system.** After "We accelerate rebuilding by
  routing records through a butterfly network," the sentence "H2O2RAM rebuilds
  each hash table with bitonic sort" leaves the reader to guess why H2O2RAM
  appears. First state the task both designs perform ("A rebuild must move each
  record to its hash-table bucket without revealing the destination"), then
  compare how each does it.

Do not fix an abrupt sentence by changing whom it credits.

## 4.5 Justify claims only with facts the reader already has ★

A *because* clause helps only if the reader can check it against what the
paper has already explained. A compressed justification that depends on an
unseen mechanism reads as a riddle:

> The routing also suits AVX-512, because every byte of a record follows the
> same route.

This is true to the author, who knows the byte-sliced layout. To a reader,
both the reason and its relevance to vector instructions are unexplained.
Explain the mechanism first, or defer the claim until the mechanism appears:

> Our buckets hold 64 records, so one AVX-512 register holds the same byte of
> every record in a bucket. Merging and splitting two buckets then takes two
> permutation instructions per byte position.

Ask what a reader who has read only the preceding text needs in order to
accept the justification.

## 4.6 Do not restate ★

If a sentence only explains the previous one again from another angle, merge
the two into one sentence that states the property and what it achieves:

> Later accesses find this copy first, so each level is searched for the key
> at most once between rebuilds. A second search would scan the same bucket
> and reveal that the key was accessed again.

becomes

> Later accesses find this copy first, so each level is searched for the key
> at most once between rebuilds, and the probes do not reveal whether the key
> is accessed again.

The same applies within a sentence. If the text has already said that the
smallest level is scanned in full, write "An access searches the levels from
smallest to largest," not "An access scans the smallest level and then
searches the larger levels from smallest to largest."

A heading does not reset the reader's memory. If a subsection ends with "A
merge-split cannot move a record directly to its output slot, because the
memory address would reveal the record's tag," the next subsection should not
open by explaining that again. Go straight to the new idea.

## 4.7 Keep different causes separate

Distinguish **why an operation happens** from **why that operation is
expensive**. If a data structure moves to disk because it exceeds physical
memory, and encryption makes each transfer more expensive, these are two
facts: capacity causes the transfer, and encryption changes its cost. Do not
collapse them into a statement suggesting that encryption made the structure
exceed memory.

---

# Part 5. Sentence Level

## 5.1 State the fact, not a label for it

A sentence that only names a category makes the reader wait for the content:

> Entry size introduces a second tradeoff.
>
> Supporting arbitrary keys requires handling unsuccessful lookups securely.
>
> \sys uses different constructions for small and large entries.

State the specific fact the paragraph builds on:

> The choice between hierarchical and tree-based ORAM also depends on entry
> size.
>
> Unlike a dense address, an arbitrary key may be absent, so a lookup can
> miss.
>
> \sys uses a hierarchical ORAM for small entries and a tree-based ORAM for
> large entries.

Words such as *securely*, *efficiently*, *different*, and *a second tradeoff*
are warning signs. Ask what exactly is secure, efficient, different, or traded
off, and write that. This rule governs sentences that are supposed to deliver
the fact. At abstract depth, naming a component and its benefit is enough
(§2.1).

## 5.2 Use concrete subjects and verbs

Write "The shard stores modified nodes," not "The recording of modified nodes
is performed by the shard." Prefer direct technical verbs (*stores, sorts,
sends, merges, rebuilds, samples, encrypts, routes, verifies, delays,
reduces*) to nominalizations such as "perform the computation of," "provide a
reduction in," or "carry out the execution of."

## 5.3 One logical unit per sentence ★

Do not join independent facts into one compound sentence because they concern
the same topic. A sentence of the form "X does A, Y does B, and Z has property
C" is justified only when the facts form one logical unit. When two clauses
have a causal or logical relation, state it with a connective (§4.3). When
they do not, use separate sentences:

> Rebuilding the index requires sorting all records. This sort dominates the
> rebuild cost.

is clearer than "Rebuilding the index requires sorting all records, and the
sort dominates the rebuild cost." The split works because "This sort" points
back to the previous sentence. Splitting without such a link produces the
robotic list of §4.3.

Punctuation:

- **Semicolons.** Use them rarely. A semicolon joining two technical claims
  usually means the sentence should become two sentences, or should use a
  real connective such as *because*, *so*, or *whereas*. Several semicolons
  in one paragraph make the prose dense and mechanical.
- **Em dashes.** Use one only for a genuine interruption. Do not use it as a
  generic replacement for a period, a colon, parentheses, or a causal
  connective. Frequent em dashes are a hallmark of generated prose.

## 5.4 Vary sentence length and structure

Do not make every sentence about twenty words long and built from the same
template. A paragraph can naturally hold one longer explanatory sentence, one
short declarative, and one sentence giving the consequence. Short sentences
suit important conclusions ("This sort dominates the rebuild cost."). Do not
merge them into neighbors to make a paragraph look sophisticated.

## 5.5 Make every reference resolve immediately

Be careful with *this, it, they, these, its, their*, especially at the start
of a sentence. "This reduces the overhead" is weak. "Sharing the sort across
levels reduces the rebuild overhead" is clear. The reader should never have to
inspect several earlier sentences to find what *this* means.

- A noun after *this* must name something the text has already presented in
  that role. "This sharing does not repeat real probes" fails if no earlier
  sentence said that anything is shared. Write the fact first ("several
  merges share one hash"), then refer to it.
- *Both* and *the two* need the same care. "Our scheme uses the same size for
  both" leaves the reader to find the two things. Name them.
- Relative clauses (*which, in which, where*) attached to a long noun phrase
  are ambiguous. In "Prior TEE-based hierarchies obtain this placement with
  oblivious sorting, in which bitonic sort is a central primitive," *which*
  could refer to three nouns, and "a central primitive" hedges what the prior
  system does. Write "H2O2RAM performs this placement with bitonic sort."

## 5.6 State conditions positively

A double negation makes the reader invert the sentence twice. "The probes
reveal nothing about the requested keys only if no level is searched twice for
the same key" becomes "Each level is searched for a key at most once between
rebuilds, so the probes do not reveal whether the key is accessed again."

## 5.7 Cover variants with one formulation

Do not add a clause for each variant of a mechanism. "Each stage therefore
makes many passes over its data, yet resolves only one tag bit, or a few when
a merge-split combines several buckets" is hard to read. "These merge-splits
make many passes over the data to resolve each tag bit" states the cost once
and already covers the multi-way case.

When parallel cases each need their own number, name the cases once and give
later numbers with *respectively*. After "about 580 instructions for 4-byte
keys and 1100 for 8-byte keys," write "takes only 16 and 64 instructions,
respectively," not "for 4-byte keys ... for 8-byte keys" in every sentence.

## 5.8 Attach each detail to the claim it supports

A prepositional phrase can imply a causal link that does not exist.
"Ramachandran and Shi adapt the approach to multicores with a multi-way
network" suggests that multicore execution requires a multi-way network, which
is false. Attach each detail to the claim it actually supports, or drop it.

## 5.9 Avoid constructions that sound generated ★

These patterns make prose sound machine-written even when every word is
accurate:

- **Uniform rhythm** across paragraphs, and paragraphs made entirely of
  definitions or classifications.
- **Generic transitions** at the start of sentences: *Moreover, Furthermore,
  Consequently, Importantly, Interestingly, Notably, Finally, As discussed
  above*. Use one only when it adds real logical information. Usually, state
  the relation instead: not "Moreover, rebuilding each level requires another
  sort" but "Because each level is rebuilt independently, the baseline
  performs another sort at every level."
- **Stacked precision signposts** such as "Informally, ... More precisely, ...
  Concretely, ...". Decide what precision the paper needs and state the claim
  once at that level.
- **Corrective contrasts.** "A needs X, not Y" or "X is set by A, not by B"
  argues against an alternative the reader never proposed ("A hash table,
  however, needs each record in its bucket, not a total order"). State what
  the design does and why it suffices. Keep a contrast only when the rejected
  alternative is prior work or an expectation readers genuinely hold, and
  name it. Overusing *rather than X* is the same habit.
- **Tacked-on elaborations.** In "A bitonic sort of \(n\) records makes
  \(\Theta(\log^2 n)\) compare-exchange passes over the data, and each
  compare-exchange moves whole records," the second clause is true but
  explains nothing the argument uses. Delete such clauses. If an implication
  matters later, state it where it is used.
- **Repetitive "This allows us to ..."** sentences, and repeated announcements
  that something is "important," "key," or "crucial."
- **Narrating discarded designs.** Write "We use a two-stage rebuild," not
  "Instead of using a single-stage rebuild, we use a two-stage rebuild." Mention
  a rejected alternative only when it is prior work, when readers would
  naturally expect it, or when the contrast explains an important decision.

Prefer concrete events and consequences: "Requests accumulate while the
rebuild runs. The scheduler therefore processes the rebuild in bounded units
between requests." Something happens, and the design responds.

---

# Part 6. Word Level

## 6.1 Use plain, conventional academic language

The target register is technical and direct, not ornate and not
conversational. Simple words are fine when they are technically appropriate.

| Prefer | Over |
|---|---|
| saturates | runs out of room |
| fails to place | cannot find room |
| reduces | cuts |
| lies in | sits in |
| must | has to |
| does not limit | is not a problem |
| is worthwhile | pays off |

Use the phrasing the field already uses. Write "uses \(3\times\) less memory
than H2O2RAM," "runs rebuilds in the background without pausing requests,"
or "makes rebuilding cheap relative to lookups." Do not replace such phrases
with accounting vocabulary ("uses 1/3 as many allocated bytes," "accounted
record storage") or with a hedge-laden paraphrase ("workers rebuild tables
while requests continue, which removes synchronous rebuilds but does not
guarantee latency"). "X times less" with \(X>1\) is standard usage. Terms such
as "allocated bytes" belong in the paragraph that defines a measurement, not
in the sentences that use its result.

## 6.2 One concept, one term

Once a term is chosen, keep it. Do not alternate between *average* and
*mean*, *request* and *query*, *record* and *entry*, *buffer* and *cache*, or
*latency* and *response time* unless they denote different concepts. Keep
terms consistent across the main text, algorithms, captions, tables, and
appendices. Keep one name per object within a passage as well: do not call the
small-entry OMAP "the hierarchy" two clauses after introducing it as an OMAP.

## 6.3 Prefer established terms, and say what they do

Do not invent a phrase when the field has a standard term. If *eviction*,
*stash*, or *write-back* describes the concept, use it. A new term creates a
definition burden and makes the reader wonder whether the concept differs from
the standard one.

Avoid terms the literature uses inconsistently. "Dynamic" can mean supporting
insertions and deletions, having a variable size, or adapting at run time, so
"a dynamic hierarchical OMAP" says nothing. Name the property: "supports
insertion and erasure by arbitrary keys."

The same holds for ordinary words that already carry several technical
meanings in the paper. "Run" can mean an execution, an experiment, or a
sorted sequence, so "each bucket is stored as one contiguous run" makes the
reader choose. Write what is meant: "the slots of a bucket are stored
together."

Write an established term so that it serves both experts and non-experts.
Keep the keyword, which lets an expert place the idea, and put it in a
sentence that says what it does: "We apply deamortization to run these
rebuilds in the background without pausing requests." Dropping the term ("we
run rebuilds in the background") hides the connection to prior work. Using it
bare ("we improve and implement deamortization") leaves non-experts behind.

## 6.4 Define everything before using it ★

A reader must be able to find each definition in the same document tier. A
symbol used in the main text cannot be defined only in the appendix. If no
term exists for a condition, such as "an idle configuration," describe the
condition directly. On first use of a term that later sentences depend on,
italicize it so a skimming reader notices it.

"Term" includes more than technical vocabulary:

- **Short derived nouns.** A text that has said only "hierarchical ORAM" and
  "hash tables of increasing size" has not defined "the hierarchy" or
  "levels," so "a hierarchy with fewer levels" is opaque in an abstract.
  Write "the number of tables each lookup probes" until the paper defines the
  structure.
- **Definite articles.** "The byte-sliced technique" points back to a
  technique the reader never met if the earlier sentence said "a byte-sliced
  layout."
- **The author's private picture.** "Each merge continues the network where
  the previous one stopped" is clear to someone who has stared at the figure.
  Spell the picture out in words the reader has: "the merges form one
  butterfly network over the final table's buckets, and each merge runs the
  next stages of it." Citing a figure does not license leaving a claim in the
  figure's terms.
- **Hardware features.** "With the VP2INTERSECT extension, available on
  processors such as AMD Zen 5, ..." assumes the reader knows the extension.
  Introduce it by what it does: "AMD Zen 5 supports the VP2INTERSECT
  extension, whose instructions compare every 4-byte or 8-byte lane of one
  register with every lane of another." This applies to every instruction
  the text names. Most readers do not know `PDEP`, so "a 128-bit mask marks
  the candidates, and `PDEP` selects the lowest four" stops them. Name an
  instruction only when the cost or security argument depends on it, and
  then say what it does. Otherwise describe the step ("a few
  bit-manipulation instructions select the lowest four") and keep the
  instruction's name in a source comment.
  If readers may not know an instruction-set extension at all, introduce it
  in the background with a generic example ("one instruction adds eight
  pairs of 64-bit integers"). Leave the specific instructions that the
  contribution relies on to the section that uses them.
- **Returning symbols.** Redefine a symbol when it returns in a new context.
  If \(n\) last meant the number of records in a rebuild, write "To sort \(n\)
  records, ..." before giving prior sorts' costs in terms of \(n\).

## 6.5 Say exactly what a quantity counts

Do not use *load, size, overhead, work,* or *capacity* when several readings
are possible. Write "the number of distinct keys sent to each shard," not "the
shard load." Say whether a quantity is global, per server, per shard, per
request, per level, amortized, or worst case. "Buckets have a fixed capacity
\(Z\)" could mean each bucket or all of them together. Write "buckets that
each hold up to \(Z\) records."

State what a count depends on. Comparing two buckets of 64 keys always takes
4096 key comparisons, but the number of instructions depends on the key size,
because a 512-bit register holds 16 keys of 4 bytes or 8 of 8 bytes. "These
4096 key comparisons take more than 1000 instructions" is true only for 8-byte
keys.

Keep independent parameters separate. A butterfly network's bucket size and a
hash table's bucket size are independent: a rebuild could route with larger
buckets and then divide each into several hash-table buckets. Define each
parameter where its concept is introduced. If the scheme sets them equal, say
so once, for example in a footnote.

## 6.6 Use numbers instead of magnitude words

Do not write *significantly faster, much smaller, reasonable time,
considerable overhead, even faster,* or *easily hides* when a number is
available. Intensifiers such as "even" and "easily" claim a size or an effort
without stating it. Give the factor, percentage, absolute latency,
throughput, memory consumption, or asymptotic difference. If no number exists
yet, write the plain claim ("faster than lookups") and leave an author note to
measure it.

Emphasis is allowed when it is earned. Plain prose need not be emotionally
flat: "Surprisingly, ...," "The useful consequence is ...," or "This is enough
to ..." can mark a turn or a satisfying resolution. For a surprise, first
establish the natural expectation and explain why the result differs. For a
simplification, name the difficulty that disappears. Do not invent surprise,
exaggerate novelty, or reuse the same cue until it becomes a formula.

## 6.7 Drop words that add nothing

- "We choose to leave older copies in place" → "We leave older copies in
  place."
- "for two main reasons" → "for two reasons," unless the text also gives the
  minor ones.
- "We improve and implement X": "implement" adds nothing in a contribution
  statement.

---

# Part 7. Specific Kinds of Content

## 7.1 Security and leakage

Whenever a step intentionally reveals information, state:

1. what the adversary observes;
2. why this does not compromise the claimed property;
3. which assumption makes the argument valid;
4. what input or behavior would violate that assumption, if relevant.

Do not hide deliberate leakage behind "this is safe."

Name the observed event itself. A secret leaks through an access at a
location that depends on it, not by "becoming a memory address." Write
"the locations the eviction reads and writes must not depend on any
block's destination," not "a block's destination must not become a memory
address," and "a register permutation accesses no memory," not "it uses no
memory address."

State what a mechanism hides, not only what it does. "Every later level
receives a dummy probe, so every access probes one bucket in each level"
describes the trace and leaves the point to the reader. Add what the adversary
cannot learn: "... so the probes do not reveal whether the key is accessed
again."

Give every link of an obliviousness argument: where the secret goes, why
the adversary cannot observe it there, and therefore which accesses stay
fixed. "Only the indices depend on the tags, so the trace reveals nothing"
skips the middle link. "The tags affect only the permutation indices, which
stay in registers, so the accesses are the same for every routing" gives
it.

Check every performance claim against the security argument. "Writes skip the
table probes, so they are faster than lookups" means a write leaves a
different trace than a lookup. That is fine only if the security definition
treats the request type as public. Say so, give the reason (the program calls
a different function for each type), and say how an application can hide the
type if it needs to (one access interface that reads, writes, or erases). A
speedup that quietly contradicts the stated leakage is a correctness error,
not a wording issue.

## 7.2 Prior work

### 7.2.1 Verify descriptions against the source

Check every precise claim about another system, construction, bound, or
primitive against the original paper, not memory, another paper's summary, an
earlier draft, or folklore.

A paper's description of its system may differ from what its artifact runs.
When a comparison depends on what the prior system executed, such as which
sort its measurements used, check the released code as well, and describe the
system that produced the reported numbers. State any discrepancy that matters
to the comparison. Record one that does not matter in a source comment.

Check the code path that actually runs. A build flag or an include does not
show that the code uses a feature the way the sentence says: a branch may be
compiled out, or the support may be an optional build that is off by
default. A sentence about several systems must hold for each of them, so
state what they share, and keep per-system details in a source comment with
the file and commit you checked.

### 7.2.2 Separate cited facts from your own analysis

If a prior paper reports bucket sizes and speedups, but the explanation for
its limited gains is yours, cite the facts and present the explanation as
yours ("One reason is ..."). Do not attribute to a paper a conclusion it never
draws.

### 7.2.3 Quote parameters as the source states them

"\(Z=512\) suffices for \(2^{-80}\)" is not the same claim as "\(Z\) is
typically greater than 512."

Do not place parameters from different sources side by side when an unstated
variable separates them. "One sort uses \(Z=512\) for \(2^{-80}\), and another
selects \(Z\) between 4096 and 16384 for \(2^{-60}\)" suggests that larger
buckets give a worse failure probability, while the actual difference is the
second sort's higher load factor. Unless the difference serves the argument,
state a bound that covers all of them: "Prior butterfly-based sorts use
buckets of at least \(Z=512\) records."

### 7.2.4 Cite at first substantive use, and credit borrowed ideas where used

Cite prior systems, algorithms, nonstandard primitives, and borrowed results
when the main text first introduces them, so the reader never searches
backward. Standard facts need no citation.

Credit a borrowed trick where it is used, and say how the setting differs. If
a prior paper caps the buckets of its structure and collects all overflow in
one shared pile, and our design caps network buckets and gives each stage its
own stash, write that we *adapt* the idea and state the difference in one
clause. Do not imply that the prior paper used the trick in our setting.

### 7.2.5 Credit shared properties to the framework

Before writing "In X, ...," check whether the property holds for every
construction in the framework. "In H2O2RAM, the level of capacity \(2^i\) is
rebuilt about every \(2^i\) accesses" suggests that H2O2RAM is unusual, although
every hierarchical ORAM does this. State a shared property as a property of
the framework, and name an instantiation only for what it changed (§3.3).

### 7.2.6 Describe a shared technique once, then the difference ★

Parallel sentences about each scheme hide what differs:

> Goldreich and Ostrovsky use a sequence of oblivious sorts. H2O2RAM builds
> all of its hash tables with bitonic sort, chosen for its concrete
> efficiency.

State the common technique first, then only the difference that matters:

> Both implement the rebuild with oblivious sorts. For practical efficiency,
> H2O2RAM's implementation uses bitonic sort, which makes
> \(\Theta(\log^2 n)\) passes over \(n\) records.

When several results matter only as a group, state the bound they share and
single out only the result that changes the picture:

> The concrete instantiations of the earlier sorts implement each merge-split
> with bitonic sort and perform \(O(n\log n\cdot\operatorname{poly}\log\log
> n)\) work. Flexway O-Sort achieves \(O(n\log n)\) work, but its concrete
> speedup over bitonic sort remains limited, especially for small entries.

Name the category of a prior mechanism instead of each paper's instance. "A
merge-split passes its records through a compaction or sorting network of
depth at least \(\log Z\)" covers every prior design. Listing each paper's
network depth adds detail without adding to the argument.

### 7.2.7 Relate a technique to prior uses without implying exclusivity

"The existing instantiations of the butterfly network are oblivious sorts"
equates two categories. "Butterfly networks have been studied in the oblivious
sorting literature" suggests no other field studied them. Write "Butterfly
networks underlie several oblivious sorting algorithms."

When prior systems used the same tool, say so where the tool is introduced,
briefly and from the angle the argument needs, such as the speedup it gave
them. Do not re-explain their design, and do not imply that their technique
requires the tool when it does not.

### 7.2.8 Quote a measurement only if it compares the operation you need

A prior paper's speedup applies to the operation it measured. A sort-versus-
sort ratio misstates a comparison where one design needs only bin placement:
there the butterfly network is the direct method, and bitonic sort needs extra
padding and compaction. Leave such a number out, and record in a source
comment why, so later revisions do not reintroduce it.

### 7.2.9 Define subtle semantics by reference to a known system

When an interface has subtle semantics, such as a batch with repeated keys,
relate it to an established system instead of listing every case: "We
deduplicate repeated keys with the same semantics as Snoopy." Verify the match
against that system's paper first. If the semantics differ slightly, write
"similar to" and state the difference only if it matters to the reader. If a
compared system has a stricter contract, such as requiring distinct keys, say
so in one clause with a citation.

### 7.2.10 Keep the comparison with prior work in view ★

The important comparison is normally **our system versus the relevant prior
baseline**. Do not spend much prose comparing two configurations of your own
system unless it explains a result. Keep internal variants subordinate: "We
outperform \(B\) by 4.1×, and the gain grows further when batching is
enabled."

When reporting an improvement, restate the baseline, the configuration, and
the improvement: "At \(N=2^{24}\), our implementation is 3.7× faster than
Baseline X." This repetition is the one deliberate exception to §2.4.

## 7.3 Quantitative claims

Before writing a number, identify the experiment or derivation, the
configuration, the exact value, and any division or normalization behind a
factor. Do not combine values from unrelated runs and phrase them as one
measurement. Derive operation counts from the code, not from a prose
description: compile the kernel, count the instructions in each loop, multiply
by the trip counts, and record the derivation (file, commit, compiler, flags)
in a comment beside the sentence.

The same headline number may appear in the abstract, introduction,
evaluation, conclusion, tables, and captions. The values must agree. Treat a
mismatch as a correctness bug.

Quantify the dominant saving. Not "Our optimization significantly reduces
sorting overhead," but "The baseline performs one sort at each of \(L\)
levels, whereas we perform one sort for the entire rebuild," followed by the
measured improvement.

Distinguish model predictions, proved guarantees, and measured behavior, and
check claims against the actual algorithm and resource lifetimes. Apply a
correction consistently to prose, tables, figures, and the scripts that
generate them.

## 7.4 Evaluation

A result subsection follows **claim → intuition → measurement conditions →
representative numbers → explanation**.

- **Open with the comparison**, not an unexplained measurement. Not "The
  latency is 23 μs at 100K requests/s," but "Our scheduler keeps latency well
  below the sequential baseline's once requests begin to queue," followed by
  why and by representative values.
- **Explain a multi-part metric first.** "End-to-end latency consists of the
  work performed for the request and the time the request waits behind earlier
  work" prepares the reader for the graph.
- **Do not narrate the graph.** The reader can see which curve rises, where
  lines cross, and where a plateau starts. Point to the figure once and give a
  few anchors, usually the low-load regime and where the main advantage
  appears.
- **Explain after reporting.** Give only the part of the design needed to
  explain the measured trend.
- **Numbers support claims; they are not the content.** State the
  qualitative claim, then give only the one or two numbers that carry it.
  Every other measurement (per-configuration ranges, secondary shapes,
  exact brackets, method details) goes in a source comment or the appendix.
  A paragraph that reads as a list of measurements has lost its argument,
  even if each number is correct.
- **State the general mechanism before a case-specific conclusion.** Write
  "Batching raises the lookup throughput, which puts more pressure on
  rebuilding," then explain which machine copes and why. Opening with
  "Batches move the bottleneck to rebuilding on the Intel machine" asserts a
  per-machine result before the text has explained what distinguishes the
  machines.
- **Compare like with like.** Do not add a baseline measured with a different
  protocol, a different workload, or analytically instead of experimentally,
  unless that difference is part of the comparison. When a reader could
  attribute the gain to hardware the baselines lack, enable the same
  hardware support in the baselines and say so in the methodology.

## 7.5 Figures ★

Prose about a figure explains why it matters, the central comparison,
representative results, and the interpretation. The caption carries the
configuration and the qualifications a reader needs while inspecting it.

Do not narrate a figure. Readers take in a drawing faster than a paragraph
listing bucket counts, colors, and which stage does what. Cite the figure for
the one claim it supports: "The merges then form one butterfly network over
the final table's buckets (Figure 5)." Bring the figure in where the argument
needs that evidence, not as the opening of a design paragraph, which should
start from the design question. The sentence must make sense to a reader who
has not yet looked (§6.4).

If one curve ends earlier than another, readers can see that. Explain the
limit only if its cause changes how the result should be read.

Two kinds of figure explain a design faster than prose:

- **Decomposition figures.** When a sequence of steps forms one familiar
  structure, draw the structure once and shade each step's part with its own
  background color. Shading the merge-splits of a 16-bucket butterfly network
  by the merge that performs them shows at a glance that incremental merges
  perform the same network as one large rebuild.
- **Timelines for parallel execution.** Give one row per thread, schematic
  lengths, and arrows for hand-offs. Show what overlaps what, especially where
  computation hides memory latency.

## 7.6 Tables

Tables answer questions. They do not catalog mechanisms. Choose columns
around what readers want to compare: storage overhead, required throughput,
average cost, worst-case cost, or supported guarantees. Put numbers, ratios,
or short formulas in quantitative columns. Component names and descriptions of
how storage is organized do not say how much storage a method uses.

- Use the same units and baseline throughout a column, and define the
  normalization once, close to the table.
- Separate average and worst-case quantities.
- Prefer a familiar expression to an auxiliary symbol defined elsewhere.
- Group closely related variants into one parameterized row when the
  comparison does not depend on listing them.
- Keep cells and captions short. Put derivations and substantial caveats in
  the text. Mark an uncertain entry precisely with an actionable author note.
- State whether a number is predicted, analytical, extrapolated, empirical,
  or incomplete (for example, because of a timeout) where it appears,
  preferably in the caption or the table, and only there.
- Build grouped column headings from shared rows so that labels align. Do not
  nest a multiline heading inside a multilevel header. Use decimal
  coefficients when stacked fractions make rows cramped.
- Inspect the rendered table at reading size for overlaps, not only compiler
  warnings.

## 7.7 Pseudocode

Use a pseudocode package such as `algpseudocode`, not hand layout with
`tabbing`, manual indentation, and `//` comments. Use numbered lines, bold
keywords, small-caps procedure names (`\textproc`), right-aligned
`\Comment`s, and `\Require`/`\Ensure` shown as **Input**/**Output**. Keep each
line short enough that its comment does not wrap. In IEEE templates, place
the `algorithmic` environment inside a `figure`, because IEEE has no algorithm
float. Define helper procedures in a short note below the pseudocode.

---

# Part 8. Drafting, Revising, and Reviewing

## 8.1 Drafting a section

1. **Establish the facts.** Read the neighboring sections, the notation
   already introduced, the relevant algorithms and appendices, the supporting
   results, and the original papers for any prior-work claim. Do not rely on
   memory for numbers or for descriptions of prior systems. Read the project's
   notes file for decisions that constrain the section.
2. **Write the section's purpose in one sentence** (§3.1).
3. **Choose the argument shape** (§3.4).
4. **Outline one purpose per paragraph.** For example: P1, why rebuild latency
   matters; P2, sorting is the dominant cost; P3, how our design removes
   repeated sorting; P4, the saving. Do not draft sentences until the sequence
   forms an argument.
5. **Draft with the main point first** in each paragraph (§4.1).
6. **Remove mechanics that do not support the argument.** For each detail,
   ask whether removing it would prevent the reader from understanding the
   claim, its cause, its correctness, or its evidence. If not, move it to an
   algorithm, the appendix, or an implementation section, or delete it.

## 8.2 Meeting a length target ★

Decide which facts the section's argument needs and delete the rest. Good
candidates:

- a problem that a later section raises and solves, such as handling absent
  keys. Raise it where it is solved;
- concrete operation counts of a prior system, such as its number of sorts,
  when the evaluation measures the result directly;
- motivation that the introduction already gives and this section does not
  use;
- a survey of prior choices that matters only to a later design decision.
  Move it to where the decision is argued.

Never reach the target by clipping sentences. Telegraphic stubs such as
"Tombstones prevent this (Section 2.4)." lean on a vague "this," reduce a
mechanism to a label, and read as machine-generated. If the fact is worth
keeping, give it a full sentence. Measure length in the compiled PDF.

## 8.3 Preserve the scientific argument ★

A request to check accuracy or improve prose is not permission to remove the
paper's substance. Keep comparison sections, tables, figures, and
explanations of novelty unless the author asks for their removal or a concrete
replacement fully serves their purpose.

If one table entry is wrong or unsupported, repair that entry: verify its
source, correct its units or assumptions, or flag it for the author. Do not
delete the table or replace a quantitative comparison with generic prose
because checking it is hard.

Correctness does not require timid writing. Look for consequential insights:
a surprising equivalence to prior work, a hidden constraint, a stronger bound,
a security invariant, or a concrete tradeoff. Do not replace such an argument
with a catalog of implementation details or safe generalities.

Before finishing, compare the revision with the original. Every removed
comparison, number, and insight must be preserved, corrected, replaced by a
stronger argument, or explicitly flagged for the author. Do not silently erase
open research questions.

## 8.4 Handle incomplete support with notes, not hedges ★

A claim whose support is incomplete keeps its target wording and gets an
adjacent author note (in the project's author-note macro) that names the
missing proof, measurement, or source:

> Sharing the index removes one full copy of the data.
> [Author note: Verify that concurrent updates do not require another full
> snapshot; the current accounting covers steady-state reads.]

Do not soften the claim, wrap it in "aims to," "is intended to," or "in our
idealized accounting," or move it out of the abstract while the note exists.
Planned results follow the same rule: a draft with a TODO for a measurement
still states what the paper will show. The note, not a weaker sentence, keeps
the claim honest until the evidence arrives. Every such note must be resolved
before submission, by evidence or by correcting the claim.

Keep established claims confident, and put each open question next to the
claim it affects, not as vague qualifications across a paragraph.

The exception is a claim known to be false, such as a sentence saying a
checker verifies every configuration when five fail. Correct it directly and
briefly. A note never licenses a known falsehood.

## 8.5 Fix inconsistencies by deleting, not explaining

When two sections disagree, do not add a third sentence explaining the
disagreement. Decide which statement is authoritative, correct or delete the
other, and replace duplicate explanations with a cross-reference. A local
correction should usually make the paper shorter. Do not write about
difficulties encountered while developing the paper unless they are
scientifically relevant.

Before deleting a statement because "it is already said earlier," check that
the earlier location says it in the main text, not only in a comment or an
author note. If it does not, move the statement there and then delete the
repetition.

## 8.6 Responding to highlighted sentences

When the author highlights sentences that "do not fit well," assume the
problem is readability, not accuracy, precision, or credit. Check, in order,
whether the sentence:

1. uses a term or name the reader has not been given (§6.4);
2. appears abruptly, without following from the previous sentence (§4.3,
   §4.4);
3. repeats nearby text, including text before a heading (§4.6);
4. names a category instead of stating the fact (§5.1); or
5. gives detail too deep for its location (§2.1).

The usual fix is to cut or reorder, not to add qualifications. Making a
deliberately vague preamble sentence more specific, or adding a citation,
leaves the actual problem in place.

## 8.7 Reviewing a draft

A review follows this guide too. Before proposing a change, classify the
problem:

1. **The sentence is false, or contradicts another part of the paper or the
   implementation.** Propose the smallest correction.
2. **The sentence is hard to read.** Apply Parts 3 to 6, and propose a
   replacement that is easier to read than the original.
3. **The sentence is true and readable, but a hostile reader could stretch
   it.** Propose no change. If an edge case matters scientifically, point to
   where the paper already handles it, or suggest an author note.

Every replacement must be at least as readable as the text it replaces. A
rewrite that is longer, adds qualifications, or introduces accounting
vocabulary is a regression unless the original was false. Do not propose
reversing a decision that the project's notes record, such as a section
order, a figure example, or a sentence's placement. Flag the conflict as a
question for the author.

Do not put blanket rules in a review, such as "a smoother sentence must not
make an unsupported claim easier to believe." Under such a rule every
readability edit becomes a scope negotiation. The remedy for an unsupported
claim is an author note (§8.4).

## 8.8 Review in two passes

First make the argument correct and coherent. Then check whether a human
reader has reasons to start, continue, and remember it. Recheck the
fundamentals after any change made for engagement.

---

# Part 9. Final Self-Check

Before returning a drafted or revised section, go through these questions.
Section numbers point to the rule, and ★ marks recurring problems.

## Paper and section structure

- Can a reader get the main idea and the comparison from topic sentences,
  figures, and tables, without studying the implementation? (§1.3)
- ★ Is each fact at the right depth: abstract, main text, appendix, author note,
  or source comment? (§2.1)
- Do the contributions open with headline numbers, and are techniques ordered
  by importance? (§2.2)
- Does the bottleneck path get most of the space and a figure, and each
  secondary mechanism only a sentence or two? (§2.3)
- ★ Is any mechanism, result, list, or caveat stated in two places, other than
  results against prior work? (§2.4)
- Does the appendix add detail rather than repeat the main text? (§2.5)
- Does every cross-reference land on what it promises, including its framing?
  Does any reference hide a decision that one sentence could state now?
  (§2.6)
- Can the section's purpose be stated in one sentence, and each subsection's
  topic be named from its title and first paragraph? (§3.1)
- Do headings name their object, fit on one line, and get their terms
  defined? (§3.2)
- ★ Is the framework explained as the closest prior system builds it, credited
  to its originator, and not overgeneralized to a whole class? (§3.3)
- Does the section follow an argument shape that fits its purpose? For a
  design choice: are both sides of a split convention cited, the deciding
  reason given first, each advantage concrete, and no prior choice presented
  as new? (§3.4)
- Are the follow-on effects of the core technique grouped as consequences?
  (§3.4)
- ★ Does the text explain reasons and leave mechanics to algorithms or the
  appendix? Does a complex mechanism get a figure-guided walk-through? (§3.5)
- ★ Is one clean construction taught first, with simplifying assumptions
  signposted and later relaxed? (§3.6)
- Is the main observation built one step per sentence, opening with what we
  do? (§3.7)
- Does each demanding passage end in a payoff, and does each example reduce
  effort? (§3.8)
- ★ Does each design passage show its difficulty before its mechanism, so the
  reader thinks along instead of receiving a reference solution? Does the
  interest come from structure and pace rather than from turn phrases and
  questions, and are those used only a few times per section? (§3.9)

## Paragraphs

- Does each paragraph have one point, stated first, and do the first
  sentences form an argument? (§4.1)
- Does every sentence have a job? (§4.2)
- ★ At each sentence boundary, can the reader tell how the sentence follows
  from the previous one? (§4.3)
- ★ Do causes, conditions, problems, and shared tasks come before results,
  effects, remedies, and prior systems? (§4.4)
- ★ Does every *because* clause rely only on facts the reader already has?
  (§4.5)
- ★ Does any sentence restate the previous one, or repeat what came just before
  a heading? (§4.6)
- Are why an operation happens and why it is expensive kept apart? (§4.7)

## Sentences

- Does any sentence name a category instead of stating the fact? (§5.1)
- Are subjects and verbs concrete? (§5.2)
- ★ Did I join unrelated facts, or overuse semicolons or em dashes? (§5.3)
- Are several consecutive sentences built from one template? (§5.4)
- Can every pronoun, *this*-noun, *both*, and relative clause be resolved
  immediately? (§5.5)
- Is any condition stated as a double negation? (§5.6)
- Did I add a clause per variant, or repeat parallel qualifiers instead of
  using *respectively*? (§5.7)
- Does any phrase imply a dependency that does not exist? (§5.8)
- ★ Did I use generic transitions, stacked signposts, corrective contrasts,
  tacked-on clauses, or narration of rejected designs? (§5.9)
- ★ Did I make a true, readable sentence longer only to block an unlikely
  misreading? (§1.4)

## Words

- Is the register plain and conventional, without accounting vocabulary in
  place of standard phrasing? (§6.1)
- Is each concept named by one term, and each object by one name? (§6.2)
- Is each established term both named for experts and explained for
  non-experts? (§6.3)
- ★ Is every term, derived noun, private picture, hardware feature, and
  returning symbol defined before use? (§6.4)
- Does every quantity say what it counts, per what, and what it depends on?
  Are independent parameters kept separate? (§6.5)
- Did I use a magnitude word where a number exists, or emphasis that is not
  earned? (§6.6)

## Content

- Does each leaking step state what is observed, why it is safe, and under
  which assumption? Does each mechanism say what it hides? Does any speedup
  contradict the security argument? (§7.1)
- Is each prior-work claim verified against the paper, and against the code
  where the comparison depends on it, on the code path that actually runs?
  (§7.2.1)
- Are cited facts kept apart from my analysis, and parameters quoted as the
  source states them and only side by side when comparable? (§7.2.2, §7.2.3)
- Is prior work cited at first use, and each borrowed idea credited where it
  is used, with the change of setting stated? (§7.2.4)
- ★ Is a shared property credited to the framework, and a shared technique
  described once before the difference? (§7.2.5, §7.2.6)
- Does every quoted measurement compare the operation the argument needs?
  (§7.2.8)
- ★ Is the prior-work baseline visible wherever a result is reported? (§7.2.10)
- Can every number be traced to a run or derivation, are operation counts
  derived from code, and do headline numbers agree everywhere? (§7.3)
- Does each evaluation subsection open with the claim, give intuition, and
  report representative values instead of narrating the graph? (§7.4)
- ★ Is each figure cited for one claim, rather than narrated? (§7.5)
- Do table columns hold comparable quantities with defined normalization,
  and average and worst case separately? (§7.6)

## Revision

- ★ Did I account for every comparison, number, and insight the revision
  removed? (§8.3)
- ★ Does each incompletely supported claim keep its wording with an adjacent
  author note, rather than a hedge? (§8.4)
- Before deleting a repeated statement, did I check that the earlier location
  states it in the main text? (§8.5)
- ★ If I shortened the text, does every sentence still read as full prose?
  (§8.2)

## Final deletion pass

For every sentence and detail, ask:

> Can I remove this without weakening the argument, correctness, security
> explanation, comparison, or evidence?

If yes, remove it. When the goal is a length target, remove whole facts, not
words from the remaining sentences (§8.2). A consequential but unresolved
claim gets an author note rather than disappearing in this pass (§8.4).
