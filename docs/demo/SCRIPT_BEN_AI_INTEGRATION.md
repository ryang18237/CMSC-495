# Demo script — Benjamin Madden, Integration Lead

**Your part:** the AI integration, the provider interface, and escalation.
**Time:** about 6 minutes. **You run the member's screen.**

Lines in quotes are for reading aloud. Lines in `code` are what you type or
click. Italics are stage directions, not speech.

---

## 1. The problem we had to solve (45 seconds)

*Start signed out, at `http://localhost:5173`.*

> "Every AI product you've seen this term needed an API key. Ours doesn't —
> and that wasn't a convenience decision, it was a constraint. This is a free
> service for veterans, the repository is shared across a team, and a key
> committed to a shared repo is a credential leak. So we had three options: a
> key in the repo, which is a non-starter; one hosted deployment that only
> works while somebody's card is on file; or run the model on the machine the
> platform is already running on."

> "We run it on the machine. There is no account, no key, no per-token cost,
> and nothing a veteran types about their service record ever leaves this
> laptop."

---

## 2. It is a real model, and it is reading their record (2 minutes)

*Click* **Continue as a member**. *You land in the chat with an empty profile.*

> "A new member has nothing on file. Watch what the assistant does with a
> question it can't ground in anything."

*Type:* `Which certification should I work toward next?`

> "It won't guess. It says it has nothing on my profile and asks for the four
> things it needs. A system that invents a background for a veteran and then
> advises them on it is worse than one that admits it's empty."

*Click the* **My profile** *tab. Add two things using the + Add button on each
card:*

- Credential → `CompTIA A+` / `CompTIA`
- Training → `Network Administration Course` / `U.S. Army`

*Back to* **Chat**. *Ask the same question again.*

> "Same question, two entries later. That's a 3-billion-parameter model
> running locally, and it's naming the next step from what I actually hold —
> Security+ builds on A+ — not from a template."

*Point at the line under the answer.*

> "Every reply says which model wrote it. That's not decoration; it's how you
> tell a real answer from a fallback, and we'll come back to that."

---

## 3. The provider interface — why this is modular (1 minute 15)

*Open `docs/AI_FEATURES.md` or just talk to it.*

> "The model sits behind one interface. There are four implementations:
> Ollama for the local model, Claude, ChatGPT, and a deterministic test
> provider. Each one is roughly a hundred lines, and the rest of the
> application has never heard of any of them — it asks the AI Integration
> service a question and gets an answer back."

> "Ollama speaks OpenAI's wire format, so our Ollama provider is a subclass of
> the OpenAI one that changes exactly three things: no credential, readiness
> probed against the machine instead of read from config, and a timeout
> measured in minutes instead of seconds — because loading model weights off a
> disk is not a network round trip."

> "That last one cost us a real bug. We inherited the request body from the
> OpenAI provider, which names the reply-length cap `max_completion_tokens`.
> Ollama reads `max_tokens`, and silently ignores fields it doesn't recognise.
> So the cap didn't fail — it vanished. One-paragraph questions generated until
> the model's own 4096-token default, blew the timeout, and escalated. The
> symptom was a dead assistant; the cause was one key name. There's a test
> pinning it now."

---

## 4. Escalation is a rule, not a guess (1 minute 30)

> "The one thing this system must never do is improvise about someone's
> benefits or eligibility. So escalation is deterministic — rules, not a
> confidence score we'd have to defend."

*Type:* `I want to speak to a human please`

> "Explicit request. Straight to a counsellor."

*Click* **New conversation**. *Type:* `What is the capital of France?`

> "Out of scope. The model is instructed to reply with a marker rather than
> answer, and the marker routes to a person. It would happily tell you it's
> Paris — we don't let it, because a service that answers trivia is a service
> that will eventually answer a benefits question it shouldn't."

> "And the third path: if the model isn't running at all, we do not fall back
> to canned text. We removed that. A member reading a fluent template with
> nothing saying a model was never called has no way to know. Now it says the
> model is down, names the command that starts it, and escalates."

*Hand to Ryan.*

> "Ryan will show you the contract all of this runs on, and how we keep it
> honest."

---

## Questions you should expect

**"Does the model go in your GitHub repo?"**
> "No — about 2 GB of weights live outside the project in Ollama's own
> storage. The repo holds the integration: a provider class, a base URL, a
> model name. Clone it and the launcher pulls the model on your machine."

**"Why such a small model?"**
> "3B runs on a laptop with no GPU, which is the constraint that matters for
> a free service. The interface is the same for a larger one — it's a setting."

**"How do you know it isn't making things up?"**
> "We constrain it to the member's own record and approved knowledge-base
> articles, every answer shows its sources, and anything outside that scope
> goes to a human. We don't claim it never errs; we claim it can't act."

**"What if someone wants Claude instead?"**
> "A key in the server's `.env`, and it appears in the member's model picker.
> Members are never asked for one — there's nowhere to enter it."
