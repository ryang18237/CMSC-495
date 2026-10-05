# Demo script — Ryan Gant, Interface Designer

**Your part:** the API contract, validation, the client, and CI/CD.
**Time:** about 6 minutes. **You run the counsellor screen and the API tab.**

Lines in quotes are for reading aloud. Lines in `code` are what you type or
click. Italics are stage directions, not speech.

---

## 1. Pick up Ben's escalation (1 minute)

*Ben has just escalated two conversations. Open a second browser window,
click* **Continue as a counsellor**.

> "Ben's two escalations are already here. This is the same data through a
> different contract — the member sends a message, the counsellor sees a case.
> Neither screen knows the other exists; they both talk to the API."

*Open the top case. Type a short reply and click* **Send reply**.

> "Sending claims the case, so two counsellors can't both answer. The member
> sees it in their own window without refreshing."

*Switch to the member window and point at the reply.*

---

## 2. The contract is the product (2 minutes)

*Switch to `http://localhost:8000/docs`.*

> "Every endpoint is documented here, and this page is generated from the
> code — it cannot drift from what the server actually does."

*Expand* `GET /api/v1/ai/providers`.

> "This is the endpoint that decides what Ben's model picker shows. It returns
> a provider id and a label. It never returns a key — there's a test that
> fails the build if a key ever appears in a response body."

*Expand* `POST /api/v1/conversations/{id}/messages`.

> "A message carries a provider **id**, never a credential. And every error
> this route can raise is documented, because we test that too: every code the
> code can emit must appear in `docs/API.md`, and every documented route must
> exist. Documentation that lies is worse than no documentation, so we made it
> a build failure."

> "Underneath that there's a validation layer the model's output has to pass
> before a member sees it — it can't claim it enrolled you, approved you, or
> determined your eligibility, and it can't echo back an account number. The
> model is not trusted to police itself."

---

## 3. Data minimisation — the part I'd defend hardest (1 minute)

> "The prompt doesn't get the member's whole record. Each type of question has
> a list of fields it's allowed to see, and the Customer Data Adapter builds
> the prompt from that list. A question about certifications doesn't get a
> separation date."

> "That matters because the data is a veteran's service record. The adapter is
> also the only component that knows the legacy personnel system exists —
> nothing else in the codebase has heard of it. Sixteen import rules enforce
> those boundaries, parsed from source, and they fail the build."

---

## 4. CI/CD — how we know it works (1 minute 30)

*Switch to the terminal.*

```
python run.py --check
```

> "This is exactly what runs on every push — same commands, same order, so
> nobody can say 'works on my machine'."

*While it runs:*

> "284 backend tests against PostgreSQL, 43 frontend tests, coverage floors
> that fail the build if they drop, lint, type checking, and a complexity
> ceiling. That ceiling has caught real problems three times — the pathway
> recommender scored a 29 on its first version and got split into four named
> helpers before it merged."

> "The suite runs against the deterministic test provider, not the language
> model — CI has no GPU and we need reproducible results. That provider used
> to be a member-facing fallback, and we deliberately removed it from the
> runtime: it's a test double, and a member reading its template text had no
> way to tell it from real advice."

*When it finishes:*

> "All green. That's the gate every one of our three branches had to pass."

---

## 5. Close (30 seconds)

> "Thirteen architecture decision records document why this is shaped the way
> it is — including the two we got wrong first and corrected: the profile that
> used to come pre-filled with data the member couldn't delete, and the
> fallback that answered when the model wasn't running."

> "The honest summary: it's a prototype, the model is small, and it will not
> make an eligibility decision — by design. What it does is take what a
> veteran has actually done and tell them what plausibly comes next, for free,
> with none of it leaving their machine."

---

## Questions you should expect

**"Is there a port mismatch / how do the pieces find each other?"**
> "API on 8000, web client on 5173, Ollama on 11434. The launcher starts all
> three and prints what it resolved."

**"What happens with two people at once?"**
> "The connection pool is created once under concurrent first requests —
> there's a test with twenty simultaneous clients that fails without the lock.
> The cache and rate-limit counters are per process, which is a documented
> limitation, not something we've papered over."

**"How much of this is actually tested?"**
> "93% combined on the backend, 89% on the frontend. The number that matters
> more: the counsellor dashboard had zero tests at Alpha. Measuring coverage
> for the first time is what told us, and that's in our metrics write-up."

**"What would you do next?"**
> "A larger model behind the same interface, shared cache and rate limiting so
> it scales past one process, and more tests on the analytics worker — it's
> our thinnest area and we say so."
