# How I used AI

_Author: **Jigar Mehta**_

## Tools

I used **Claude Code** as a coding partner for the code, the tests and the first drafts of these
documents. I used **RTK** to keep the terminal output short, so the AI wasn't reading thousands of
lines of noise. I also wrote a `CLAUDE.md` file and a few "skills" in `.claude/skills/` that tell the
AI the rules of this project (for example: change the API contract first, send every error through
one place, no inline CSS), so it followed them every time.

## What the AI got wrong

1. **It wrote code for an old version of the MCP library.** The installed version (2.3) works
   differently, especially for asking a person to approve something. I found this from errors in a
   small test script, then read the library's own code before writing the real tools.
2. **It wrote a weak test that hid a real bug.** One test was meant to check what happens if a case
   changes while the approval prompt is open. The test accepted either result, so it passed. When I
   checked by hand, a person's "yes" was being used for a newer version of the case that they had
   never seen. I fixed it by tying the approval to the case version. The full story is in
   `mcp/demo/TRANSCRIPT.md`.
3. **A setup mistake made data quietly disappear.** Some request models were written inside a
   function, and FastAPI couldn't read them. Nothing crashed, but the customer page said usage data was
   missing even though everything was working. A quick manual check caught it.
4. **One test wasn't checking anything.** The test that compares the code with the API contract found
   no routes at all, because this version of FastAPI stores them differently. I noticed because it said
   every route was missing.
5. **React screens loaded data in a risky way.** New lint rules flagged four places. Besides extra
   re-rendering, an old, slow response could overwrite a newer one. I moved the loading into a small
   shared hook that ignores old responses.
6. **It missed some edge cases.** I added about 80 edge-case tests and switched the fake systems off
   for real in Docker. That found five problems:
   - comments made of only spaces were accepted
   - a broken reply from another system gave error 503 instead of the 502 the contract promises
   - the case search waited for two systems one after the other, so an outage took 10 seconds instead of 5
   - the console said "No cases match" when loading had actually failed
   - the console had no time limit on requests

   I fixed all of them, and each one now has a test.
7. **Smaller things.** A missing pair of quotes broke the API contract file, one Tailwind version
   crashed during the build (so I moved to a newer one), and there were a few typos in tests.

## How I checked the AI's work

- 182 automated tests. A single warning fails the whole run. The code also passes ruff, mypy and
  ESLint with zero warnings. The contract tests compare real responses with `openapi.yaml`, and fail
  if the code and the contract don't match.
- The Postman suite (every endpoint, 78 checks) passes against both the local app and Docker, even
  when run twice. The Docker images build with no warnings, the containers start healthy, and the API
  does not run as root.
- I clicked through the console in a browser, and I used the MCP server for real. I checked that the
  signed webhook arrived and that both audit logs share the same tracking ID.
- **Not checked:** `agent_demo.py` with the Anthropic API, because I didn't have an API key.
