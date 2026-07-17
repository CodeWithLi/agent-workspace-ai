# Chat Workspace

This page overrides the master layout only where a conversational workspace needs a more focused reading flow.

## Structure

- Use a 292px Agent and conversation rail beside the main conversation.
- Keep messages in a centered 900px reading column.
- Assistant responses are unboxed content with a visible AI identity; user messages use a quiet right-aligned surface.
- Keep execution traces inside the message flow and collapsed by default.
- Anchor the composer below the scrollable message region so long answers never push it off screen.

## Interaction

- The composer starts at one row and grows to six rows without resizing the surrounding layout.
- Sending uses the familiar arrow icon with an accessible label and disabled/loading states.
- Streaming begins with a subtle typing indicator and respects reduced-motion preferences.
- Always label generated content as AI output.

## Responsive

- Below 900px, stack the Agent rail above the conversation.
- At 640px and below, use a 176px Agent rail and retain a 40px send target.
- The conversation and composer must not create page-level horizontal scrolling at 390px.
