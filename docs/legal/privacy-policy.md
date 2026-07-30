> **DRAFT — NOT LEGAL ADVICE.** This document was drafted from an inventory of
> PrismAI's actual data flows to give your lawyer a substantive starting point.
> It **must be reviewed by qualified counsel** before publication, and every
> `[TODO: …]` placeholder must be filled in. Jurisdiction-specific sections
> (GDPR/UK GDPR/CCPA) are included as scaffolding; counsel should confirm which
> apply to you.

# PrismAI Privacy Policy

**Last updated:** [TODO: publication date]

This Privacy Policy explains how [TODO: legal entity name] ("**PrismAI**," "**we**,"
"**us**") collects, uses, shares, and protects information when you use the PrismAI
meeting-intelligence application and related services (the "**Service**").

By using the Service, you agree to this Policy. If you do not agree, do not use the
Service.

---

## 1. Who we are

The Service is operated by [TODO: legal entity name], located at [TODO: registered
address]. For privacy questions, contact us at [TODO: privacy contact email].

[TODO: If you have an EU/UK presence or serve EU/UK users, name your Data Protection
Officer / EU-UK representative here, or state that none is required.]

## 2. Scope

This Policy covers the PrismAI web application, its backend API, and the meeting
assistant bot that can join your video meetings. It does not cover third-party
services you separately connect to PrismAI (e.g. Google, Microsoft, Slack, Jira,
Linear, Notion), which are governed by their own privacy policies.

## 3. Information we collect

**a. Account & identity.** When you sign in with Google or Microsoft SSO, we receive
your email address and a unique account identifier. We do not receive or store your
Google/Microsoft password.

**b. Meeting content.** Depending on how you use the Service, we process and store:
- **Transcripts** of meetings (from pasted text, uploaded audio, or our meeting bot).
- **Audio/video recordings** captured by the meeting bot. Recordings are **hosted by
  our recording provider, Recall.ai**, and referenced by our systems; we retrieve
  them to generate transcripts and playback.
- **AI-generated analysis** derived from transcripts — summaries, decisions, action
  items, sentiment, health scores, and similar outputs.
- **Live meeting audio**, streamed transiently for real-time transcription and the
  bot's spoken/typed responses. Live audio is processed in transit and is not stored
  as a separate audio file by us (the durable recording is the one hosted by Recall.ai).

**c. Documents & knowledge base.** Files you upload (PDF, DOCX, TXT/Markdown), URLs
you submit, and content from connected sources (Notion, Google Drive) that you add to
your knowledge base. We store the extracted text and vector embeddings to power
retrieval and grounding.

**d. Chat & images.** Your conversations with the in-app assistant, and any images you
paste or upload into chat.

**e. Calendar data.** If you connect Google Calendar or Microsoft Outlook, we read
upcoming event details (title, time, attendees) to match meetings to workspaces and
enable auto-join and briefing features. We fetch these live and do not maintain a
standing copy of your full calendar.

**f. Integration credentials.** When you connect a third-party tool, we store the
access/refresh tokens or API keys needed to act on your behalf (Google, Microsoft,
Slack, Jira, Linear, Notion). These are stored server-side and are not exposed to your
browser. [TODO: counsel to confirm encryption-at-rest representations — see §10.]

**g. Usage & technical data.** Standard operational data such as IP address, request
timestamps, and error logs, used to operate, secure, and rate-limit the Service.

## 4. How we use your information

We use the information above to:
- provide the Service — transcription, meeting analysis, knowledge retrieval, the
  assistant, and the meeting bot;
- act on your explicit instructions (e.g. send an email, create a Jira/Linear issue,
  post to Slack, add a calendar event);
- generate briefings, follow-ups, and cross-meeting insights;
- operate, secure, debug, and improve the Service;
- comply with legal obligations.

**We do not sell your personal information.** [TODO: confirm — if any "sale"/"share"
as defined by CCPA occurs, this must change.]

**AI model training.** [TODO: State your position explicitly. Recommended and assumed
here: "We do not use your meeting content to train our own AI models, and our AI
subprocessors do not train their models on data submitted through their APIs under the
terms we have with them." Confirm this against each subprocessor's API data-usage terms
before publishing — see §5.]

## 5. AI processing and subprocessors

To provide the Service we share the minimum necessary content with the following
subprocessors. Each processes data only to perform its function for us.

| Subprocessor | Purpose | Data shared |
|---|---|---|
| **Anthropic** (Claude) | Meeting analysis, retrieval, synthesis | Transcript text and analysis context |
| **OpenAI** | Live assistant, dashboard chat, audio transcription (Whisper), text embeddings, fallback analysis | Transcript/chat text, uploaded audio, document text |
| **Recall.ai** | Meeting bot join + audio/video **recording hosting** | Meeting join URL, meeting audio/video, participant roster, in-meeting chat |
| **Deepgram** | Speech-to-text transcription | Meeting audio |
| **Cartesia** and/or **ElevenLabs** | Text-to-speech for the bot's voice | Text of the bot's replies |
| **Tavily** | Web search / URL content extraction for grounding | Your search query text and submitted URLs |
| **Supabase** | Database, authentication, and file storage hosting | All stored account data, transcripts, documents, images |
| **Render** | Backend application hosting | All data in transit through the Service |
| **[TODO: frontend host]** (GitHub Pages / Vercel — confirm live host) | Static web app hosting | No server-side personal data (static assets only) |

[TODO: Maintain this as your authoritative subprocessor list. Counsel should confirm
whether you must publish it and offer advance notice of changes, especially under
GDPR/DPA obligations. Confirm data-processing terms/DPAs are in place with each.]

## 6. Third-party services you connect

When you connect an external tool, PrismAI accesses it **on your behalf** using the
permissions you grant:

- **Google** — we request the scopes: read-only Calendar, Calendar events, Gmail send,
  Gmail read, and read-only Drive. We use these to read your calendar, send emails you
  approve, and ingest Drive documents you choose to add.
- **Microsoft** — we request calendar read access (and sign-in/offline access) to read
  your Outlook calendar.
- **Slack, Jira, Linear, Notion** — we use the credentials you provide to create issues,
  post messages, export summaries, or ingest documents, as you direct.

You can disconnect any integration at any time in the app, which removes the stored
credentials for that integration.

### AI assistant connectors (Claude, ChatGPT)

You may connect a third-party AI assistant — such as Anthropic's Claude or OpenAI's
ChatGPT — to your PrismAI account using our connector. When you authorize a connection:
- You grant that assistant **read-only** access to your meeting data — your open action
  items, meeting summaries and decisions, and search results across your meetings and
  knowledge base (including the workspaces you belong to). The connector **cannot**
  modify, delete, or send anything.
- Access is granted per-account via a standard authorization flow; you authenticate and
  approve on a PrismAI consent screen, and PrismAI issues a revocable access credential
  to that assistant.
- Once you connect, the data you retrieve through the assistant is processed by **that
  assistant's provider under its own privacy policy and terms** (e.g. Anthropic's or
  OpenAI's), which are outside PrismAI's control.
- You can **revoke** a connection at any time from Integrations → Claude / ChatGPT in
  PrismAI (and/or from the assistant's own connector settings), which immediately stops
  further access.

### Google API Limited Use disclosure

PrismAI's use and transfer of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the **Limited Use** requirements. Specifically:
- We only use Google user data to provide and improve the user-facing features you
  request (calendar matching/briefing, sending emails you approve, ingesting Drive
  documents you add).
- We do not transfer Google user data to third parties except as necessary to provide
  those features, for security, or to comply with applicable law.
- We do not use Google user data for advertising.
- We do not allow humans to read Google user data unless we have your consent for
  specific messages, it is necessary for security or to comply with law, or the data
  has been aggregated and anonymized.

[TODO: Gmail read/send are "restricted" scopes. Publishing this Policy at a public URL
and completing Google's OAuth verification (and, for restricted scopes, potentially an
annual security assessment) are prerequisites. Confirm the equivalent Microsoft
Graph/limited-use commitments.]

## 7. When we disclose information

We disclose information only:
- to the subprocessors in §5, to operate the Service;
- to third-party tools you explicitly connect and instruct (§6);
- **within your workspace** — when you save a meeting to a shared workspace, its
  content and derived insights become visible to other members of that workspace;
- to comply with law, legal process, or enforceable governmental requests;
- to protect the rights, property, or safety of PrismAI, our users, or the public;
- in connection with a merger, acquisition, or asset sale, subject to this Policy.

## 8. Data retention and deletion

- You can **delete individual meetings, chats, and knowledge documents** at any time in
  the app; deleting a meeting also removes its transcript from our retrieval index.
- Deleted knowledge documents are soft-deleted and [TODO: confirm — the schema
  contemplates a 30-day hard-delete; verify whether the scheduled purge is implemented,
  and state the true retention period].
- **Account deletion:** [TODO: There is currently no self-serve "delete my account"
  control. Either build one before publishing, or state the process here — e.g. "email
  [privacy contact] to request deletion of your account and associated data, which we
  will complete within [TODO: N] days." Deleting your underlying auth account cascades
  to remove your stored rows.]
- **Recordings hosted by Recall.ai:** [TODO: Deleting a meeting removes our reference to
  the recording; confirm and describe whether/when the recording is also deleted from
  Recall.ai, and Recall.ai's own retention.]

## 9. Security

We protect your information with measures including: encrypted transport (HTTPS),
server-side-only handling of integration secrets, scoped access controls, and rate
limiting on public endpoints. [TODO: Add only the safeguards you can truthfully attest
to — encryption at rest, access logging, least-privilege, etc. Do not overstate.]

No method of transmission or storage is completely secure, and we cannot guarantee
absolute security.

## 10. International data transfers

The Service is operated from, and stores data in, [TODO: hosting region(s) — confirm
your Supabase/Render regions]. If you access the Service from outside that region, your
information may be transferred to and processed there. [TODO: If you serve EU/UK users,
counsel should address the transfer mechanism, e.g. Standard Contractual Clauses.]

## 11. Your rights

Depending on where you live, you may have rights to access, correct, delete, or port
your personal information, to object to or restrict certain processing, and to withdraw
consent. To exercise these rights, contact [TODO: privacy contact email].

[TODO: EU/UK (GDPR) — add lawful bases for each processing purpose, the right to lodge a
complaint with a supervisory authority, and your DPO/representative if applicable.]
[TODO: California (CCPA/CPRA) — add the categories of information, the notice of no sale,
and the non-discrimination statement, if California residents use the Service.]

## 12. Children

The Service is not directed to, and we do not knowingly collect personal information
from, children under [TODO: 13 / 16 — set per applicable law].

## 13. Changes to this Policy

We may update this Policy from time to time. Material changes will be communicated by
[TODO: email / in-app notice], and the "Last updated" date above will change.

## 14. Contact

[TODO: legal entity name]
[TODO: registered address]
[TODO: privacy contact email]
