from app.agent.epic import draft_epic
import json

test_inputs = [
    """Elena (Customer Satisfaction SME): Wait, sorry to interrupt Sarah, but look—the queues are literally burning up with this exact issue right now. Users do not care about the standard calorie counts or macro breakdowns anymore. They are opening tickets left and right because they scan something that looks completely healthy on paper, but then they read the fine print and see it's packed with industrial emulsifiers and shelf-stabilizers. They feel completely tricked by us if our app doesn't call out that it's heavy ultra-processed junk. If we want to save our App Store rating this quarter, this entire feature needs to focus strictly on stripping back the curtain on ultra-processing. Nothing else.

Sarah (Product Owner): No, you’re 100% right, let’s pivot. Let's completely freeze any work on other features or general nutrition adjustments for this sprint. We focus solely on ultra-processing visibility. So, high level... when someone scans a barcode, the backend engine has to instantly tell them if the item has low, moderate, or high industrial manipulation. 

Elena (Customer Satisfaction SME): Yes! But look, it can't just be a random badge or a vague score, or my team is just going to get flooded with a million "Why did my food get this rating?" emails anyway. The system has to actually dig into the raw text string of the ingredients and explicitly flag the actual culprits. Like, if it sees high-fructose corn syrup, hydrolyzed proteins, or cosmetic texturizers, it needs to isolate those specific chemical markers instantly. 

Sarah (Product Owner): Okay, let me write this down. So the pipeline has to ingest the vendor catalogs, tokenize the messy ingredient text arrays, and cross-reference them against a master additive risk dictionary to count the industrial markers. It calculates the tier based only on that processing depth, writes the classification to the database, and pushes it out. I'll make sure the engineering documentation is explicitly locked down to just this ultra-processing logic so the dev team doesn't get sidetracked by other metrics.
""",
    """
JIRA-9108: Refine Premium Mobile Subscription Payment Gateway Handshake

Description:
Clean up the intermittent timeout errors occurring during the backend validation sequence of the in-app purchase flow. The core commerce service must reliably intercept the incoming transaction tokens from Apple Billing and Stripe APIs, execute a secure server-side validation check, and immediately toggle the user status to 'PREMIUM_ACTIVE' inside DynamoDB. 

Ensure that if the webhook response takes longer than 2.5 seconds, the application invokes a lightweight, asynchronous retry loop up to three times while keeping a secure spinning state active on the mobile interface. If all retries fail, seamlessly push the payload into the High-Priority Billing Recovery Queue and route a localized warning message to the client's screen to avoid drop-offs.

    """
]

for i, text in enumerate(test_inputs, 1):
    print(f"\n--- Test {i} ---")
    result = draft_epic(text)
    print(json.dumps(result, indent=2))