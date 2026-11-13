# Voice — listening first (design)

This is a design for a later build, written on Day 26 (13 November 2026,
America/Chicago). Nothing here is running in Caravan yet. Caravan can
already download speech models (Day 24), but it cannot use them. Those
rows still say they are download only.

The first useful step is listening: you talk, Caravan writes the words
into the chat box, and you send as usual. Spoken replies wait until
listening feels right.

## How it should feel

- A microphone button sits next to Send in the chat box. Press to talk,
  press again to stop.
- The words appear in the "Ask Caravan…" box so you can edit them, then
  press Send as usual.
- The browser asks for microphone permission once.
- The first time you press the microphone, Caravan gets a listen model
  ready in the background on the 1st Mac, and shows a short line such as
  "Getting ready to listen…". It does not unload the chat model to do
  this, and you do not press Load on a speech row as if it were the
  chat model.
- Spoken replies are a later step, off by default. A quiet speaker
  control and a Settings switch would turn them on, and Caravan would
  read the reply after it finishes. Live, word-by-word speech can wait.
- Extra choices (which listen model, which speak model, which voice,
  how fast) belong under Advanced. On the Models page, speech models
  that Caravan can actually use should say so, not "Download only."

## Where it runs

Always on the 1st Mac, in a small worker of its own, beside the chat
model. These models are compact and are not built to be split across
Macs; they should never be. Unloading the chat model should leave
listening in place, and the other way around. Before loading, Caravan
checks that there is enough free memory and refuses in a plain sentence
if there is not, offering a smaller model when one is already on this
Mac. Listening stays unloaded until someone uses the microphone, so it
does not sit in memory unused. Caravan will not download a listen model
on its own; it uses one already on this Mac, or asks you to download it
first.

Audio work must not stand in the chat model's one-at-a-time line, and
must not kick the chat model out of memory.

## For other apps (planned)

The same address other apps already use for chat would also accept a
recording and return text, so a helper app can talk to Caravan without
a second server. Spoken audio would follow in a later step. Start with
WAV, so a separate audio tool is not required for the first step.

## First build, when we start it

1. Confirm that a listen library sits cleanly with the locked Mac
   packages. If a broader audio library fights those packages, use a
   smaller listen-only library for this step.
2. A microphone button that puts words in the chat box.
3. A background listen worker on the 1st Mac, using a listen model
   already on disk (the default we have in mind is the Parakeet model
   already offered for download), loaded the first time the microphone
   is used.
4. The "send a recording, get text back" address on the same URL as
   chat.
5. Tests with a fake listen worker and a tiny fixture recording: the
   address shape, speech as a companion not a chat replacement, a
   memory refusal when there is not enough room, and Settings that
   stick.

Live checks on the 1st Mac and 2nd Mac wait until Brenden is ready.

## Later

- Spoken replies, off by default, and an address that turns text into
  audio.
- Other listen models as a fallback, more voices, and streamed speech.
- A short note in the client guide for apps that want to use these
  addresses.

## Risks to watch

- A new listen library fighting the locked chat packages.
- The listen worker and a large or split chat model sharing one Mac's
  memory.
- Browser recordings arriving in a format we did not plan for.
- The microphone not being offered on a page that is not a trusted
  local address.
- Giving credit for models that require it.
- Accidentally treating a speech folder as a chat Load.

See also [Day 26](DAY26.md), [browser controls](WEB.md),
[Models](MODEL_PICKER.md), and [client integration](INTEGRATING.md).
