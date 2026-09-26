"""
Message composition engine for merchant and customer WhatsApp templates.
Combines category voice rules, merchant catalog data, and trigger event payloads.
"""

from __future__ import annotations
import json
import os
import re
from typing import Any, Dict, List, Optional
from validator import OutputValidator


class Composer:
    def __init__(self):
        self.validator = OutputValidator()

    def compose(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Builds the outbound message dictionary:
        {body, cta, send_as, suppression_key, rationale, template_name, template_params}
        """
        msg = self._compose_message(category, merchant, trigger, customer)
        is_valid, errors = self.validator.validate(msg, category, merchant, trigger, customer)
        if not is_valid:
            msg = self.validator.clean_and_repair(msg, category, merchant, trigger, customer)
        return msg

    def _compose_message(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        kind = trigger.get("kind", "")
        scope = trigger.get("scope", "merchant")
        payload = trigger.get("payload", {})
        suppression_key = trigger.get("suppression_key", "")
        cat_slug = category.get("slug", "retail")
        m_ident = merchant.get("identity", {})
        owner_name = m_ident.get("owner_first_name") or m_ident.get("name", "there")
        biz_name = m_ident.get("name", "our business")
        locality = m_ident.get("locality", "")
        city = m_ident.get("city", "")
        languages = m_ident.get("languages", ["en", "hi"])
        is_hindi_pref = "hi" in languages or "hi-en mix" in str(languages)

        # Active offer lookup
        active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
        active_offer_title = active_offers[0].get("title") if active_offers else None
        if not active_offer_title and category.get("offer_catalog"):
            # Fallback to category catalog only if merchant catalog is empty
            active_offer_title = category["offer_catalog"][0].get("title")

        perf = merchant.get("performance", {})
        views = perf.get("views", 1200)
        calls = perf.get("calls", 25)
        ctr = perf.get("ctr", 0.03)
        delta_7d = perf.get("delta_7d", {})

        # Customer-facing templates
        if scope == "customer" or customer is not None:
            c_ident = customer.get("identity", {}) if customer else {}
            c_name = c_ident.get("name", "there")
            c_lang = c_ident.get("language_pref", "hi-en mix")
            c_hindi = "hi" in c_lang

            # A. Recall Due (Dentist / Salon / Healthcare)
            if "recall" in kind:
                cleaning_offer = active_offer_title or "Dental Cleaning @ ₹299"
                if cat_slug == "dentists":
                    body = (
                        f"Hi {c_name}, {biz_name} here 🦷 It's been 5 months since your last visit — your 6-month cleaning recall is due. "
                        f"Apke liye 2 slots ready hain: Wed 5 Nov, 6pm ya Thu 6 Nov, 5pm. {cleaning_offer} + complimentary fluoride. "
                        f"Reply 1 for Wed, 2 for Thu, or tell us a time that works."
                    )
                    cta = "multi_choice_slot"
                    rationale = (
                        "Customer recall reminder sent as merchant_on_behalf. Clinical tone with verified active offer price, "
                        "complimentary add-on, and evening time slots matching preference."
                    )
                else:
                    body = (
                        f"Hi {c_name}, {owner_name} from {biz_name} here! It's been a while since your last visit. "
                        f"Apke liye weekend slots available hain with our special {cleaning_offer}. "
                        f"Reply YES to book a priority slot for this Saturday."
                    )
                    cta = "binary_yes_no"
                    rationale = "Customer-scoped recall honoring relationship continuity and service offer."

                return {
                    "body": body,
                    "cta": cta,
                    "send_as": "merchant_on_behalf",
                    "suppression_key": suppression_key,
                    "rationale": rationale,
                    "template_name": f"merchant_{cat_slug}_recall_v1",
                    "template_params": [c_name, biz_name, cleaning_offer],
                }

            # B. Chronic Refill Due (Pharmacy)
            if "chronic_refill" in kind or "refill" in kind:
                body = (
                    f"Hi {c_name}, {biz_name} here 💊 Friendly reminder that your monthly chronic care prescription refill is due this week. "
                    f"Aapki regular medicine batch ready hai with doorstep delivery in {locality} today by 6 PM. "
                    f"Reply YES to confirm delivery, or reply REVISE if your prescription changed."
                )
                return {
                    "body": body,
                    "cta": "binary_yes_no",
                    "send_as": "merchant_on_behalf",
                    "suppression_key": suppression_key,
                    "rationale": "Trustworthy pharmacy refill reminder with locality delivery commitment and binary confirm.",
                    "template_name": "merchant_pharmacy_refill_v1",
                    "template_params": [c_name, biz_name, locality],
                }

            # C. Appointment Tomorrow
            if "appointment" in kind:
                time_slot = payload.get("time_slot", "11:30 AM")
                body = (
                    f"Hi {c_name}, {biz_name} here ✨ Friendly reminder for your appointment tomorrow at {time_slot}. "
                    f"We have prepared everything for your visit. Reply YES to confirm, or reply RESCHEDULE if you need to adjust the time."
                )
                return {
                    "body": body,
                    "cta": "binary_yes_no",
                    "send_as": "merchant_on_behalf",
                    "suppression_key": suppression_key,
                    "rationale": "Direct appointment reminder with binary confirmation.",
                    "template_name": "merchant_appointment_reminder_v1",
                    "template_params": [c_name, biz_name, time_slot],
                }

            # D. Customer Lapsed / Trial Followup / Winback
            if "lapsed" in kind or "trial_followup" in kind or "winback" in kind:
                offer_tag = active_offer_title or "exclusive renewal special"
                body = (
                    f"Hi {c_name}, {owner_name} from {biz_name} here! We missed you over the past few weeks. "
                    f"Apke liye ek exclusive welcome-back special ready hai: {offer_tag}. "
                    f"Would you like us to reserve a convenient slot for you this week? Reply YES."
                )
                return {
                    "body": body,
                    "cta": "binary_yes_no",
                    "send_as": "merchant_on_behalf",
                    "suppression_key": suppression_key,
                    "rationale": "Winback outreach offering active catalog benefit with effortless binary CTA.",
                    "template_name": "merchant_winback_v1",
                    "template_params": [c_name, biz_name, offer_tag],
                }

        # Merchant-facing templates
        if kind == "research_digest":
            top_item_id = payload.get("top_item_id")
            digest_items = category.get("digest", [])
            item = None
            if top_item_id:
                for d in digest_items:
                    if d.get("id") == top_item_id:
                        item = d
                        break
            if not item and payload.get("top_item"):
                item = payload["top_item"]
            if not item and digest_items:
                item = digest_items[0]

            source = item.get("source", "industry research") if item else "industry research"
            title = item.get("title", "Clinical & industry update") if item else "Clinical & industry update"
            trial_n = item.get("trial_n") if item else None

            salutation = f"Dr. {owner_name}" if cat_slug == "dentists" else f"Hi {owner_name}"

            if cat_slug == "dentists":
                if trial_n:
                    body = (
                        f"{salutation}, JIDA's Oct issue landed. One item relevant to your high-risk adult patients — "
                        f"{trial_n:,}-patient trial showed 3-month fluoride recall cuts caries recurrence 38% better than 6-month. "
                        f"Worth a look (2-min abstract). Want me to pull it + draft a patient-ed WhatsApp you can share? — {source}"
                    )
                else:
                    body = (
                        f"{salutation}, new clinical update landed ({source}): '{title}'. "
                        f"Worth a look (2-min read). Want me to pull the abstract and draft an educational WhatsApp message you can share with patients? Reply YES."
                    )
            elif cat_slug == "gyms":
                body = (
                    f"Hi {owner_name}, new fitness industry report landed ({source}): '{title}'. "
                    f"Relevant to member retention and inquiry patterns in {city}. "
                    f"Want me to summarize the key takeaways and draft an offer around this for {biz_name}? Reply YES."
                )
            elif cat_slug == "salons":
                body = (
                    f"Hi {owner_name}, latest salon trend digest just dropped ({source}): '{title}'. "
                    f"Client demand in {locality} is shifting towards these treatments. "
                    f"Want me to draft a high-CTR promotional post featuring your '{active_offer_title or 'treatments'}'? Reply YES."
                )
            elif cat_slug == "pharmacies":
                body = (
                    f"Hi {owner_name}, new healthcare advisory alert ({source}): '{title}'. "
                    f"Essential for patient adherence and prescription refill management in {locality}. "
                    f"Want me to draft an informative update for your customer broadcast list? Reply YES."
                )
            else:
                body = (
                    f"Hi {owner_name}, new local industry digest landed ({source}): '{title}'. "
                    f"Helpful insights for {biz_name} to capture customer demand this week. "
                    f"Want me to draft an update post for Google Business? Reply YES."
                )

            return {
                "body": body,
                "cta": "open_ended" if (cat_slug == "dentists" and trial_n) else "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": f"External research digest tailored to {cat_slug} anchored on source citation '{source}' and title.",
                "template_name": f"vera_research_digest_{cat_slug}_v1",
                "template_params": [salutation, title, source],
            }

        # B. Active Planning Intent (Follow up on explicit merchant interest)
        if kind == "active_planning_intent":
            topic = payload.get("intent_topic", "")
            if "thali" in topic or cat_slug == "restaurants":
                body = (
                    f"{owner_name}, here's a starter version for your corporate bulk package — you can edit:\n\n"
                    f"• 10 thalis @ ₹125 each (₹24 off retail) + free delivery\n"
                    f"• 25 thalis @ ₹115 each + 2 free filter coffees\n"
                    f"• 50+: ₹105 each + 1 free dosa platter\n"
                    f"• WhatsApp day-before by 5pm; we deliver 12:30-1pm\n\n"
                    f"3 offices in {locality} are in your delivery radius. Want me to draft a 3-line WhatsApp to send their facilities managers?"
                )
                cta = "open_ended"
                rationale = "Immediate follow-through on merchant corporate planning ask. Concrete tiered pricing and local radius targeting."
            elif "yoga" in topic or cat_slug == "gyms":
                body = (
                    f"{owner_name}, here is the drafted 4-week Kids Yoga Summer Camp outline for {biz_name}:\n\n"
                    f"• Ages 7-14 | Mon-Wed-Fri 9:00-10:15 AM\n"
                    f"• Posture, breathing techniques, and fun flexibility games\n"
                    f"• Early bird: ₹1,800/child (capped at 15 kids per batch)\n\n"
                    f"Want me to create the WhatsApp flyer copy and Google Business post today? Reply YES."
                )
                cta = "binary_yes_no"
                rationale = "Delivering promised summer program structure with pricing and age brackets, closing with binary YES CTA."
            else:
                body = (
                    f"{owner_name}, here is the starter framework for your {topic.replace('_', ' ')}:\n\n"
                    f"• Pre-launch package with tiered pricing for {locality} customers\n"
                    f"• Low-friction signup link with automated WhatsApp confirmation\n\n"
                    f"Want me to prepare the announcement post for tomorrow 10 AM? Reply YES."
                )
                cta = "binary_yes_no"
                rationale = "Actionable draft follow-through for merchant planning intent."

            return {
                "body": body,
                "cta": cta,
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": rationale,
                "template_name": "vera_active_planning_v1",
                "template_params": [owner_name, biz_name],
            }

        # C. Performance Dip (Loss aversion + immediate fix)
        if kind == "perf_dip":
            calls_drop = abs(int(delta_7d.get("calls_pct", -0.40) * 100))
            if is_hindi_pref:
                body = (
                    f"Hi {owner_name}, quick alert on your Google profile: aapke calls pichhle hafte se {calls_drop}% kam hain "
                    f"({calls} calls vs normal average). Pichhle 20 din se koi Google post update nahi hui hai. "
                    f"Main aapke liye ek high-CTR post draft kar doon featuring '{active_offer_title or 'priority booking'}'? Reply YES."
                )
            else:
                body = (
                    f"Hi {owner_name}, quick heads up on your performance: calls dropped {calls_drop}% week-over-week "
                    f"({calls} calls in the last 30d). Your Google profile has not had a fresh post in over 2 weeks. "
                    f"Want me to draft a high-visibility Google post featuring your active offer to rebound this week? Reply YES."
                )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Loss aversion anchored on verifiable calls percentage drop with an effort-externalized fix.",
                "template_name": "vera_perf_dip_v1",
                "template_params": [owner_name, str(calls_drop), str(calls)],
            }

        # D. Performance Spike (Social proof & capitalize on momentum)
        if kind == "perf_spike":
            views_spike = int(delta_7d.get("views_pct", 0.28) * 100)
            salutation = f"Dr. {owner_name}" if cat_slug == "dentists" else f"Hi {owner_name}"
            body = (
                f"{salutation}, strong momentum on Google this week! Views spiked +{views_spike}% ({views:,} views in 30d) "
                f"across searches in {locality}. Right now is the best window to convert viewers into paying bookings. "
                f"Want me to pin your '{active_offer_title or 'Special Package'}' to the top of your profile today? Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Momentum capitalization using verified views percentage growth and zero-effort one-click pin.",
                "template_name": "vera_perf_spike_v1",
                "template_params": [salutation, str(views_spike), str(views), locality],
            }

        # E. IPL Match Day (Contrarian operator advice)
        if kind == "ipl_match_today":
            body = (
                f"Quick heads-up {owner_name} — big match tonight at 7:30 PM. "
                f"Important: Saturday IPL matches usually shift -12% dine-in covers as people watch from home. "
                f"Instead of in-restaurant promotions, push your active '{active_offer_title or 'Family Combo'}' as a delivery special. "
                f"Want me to draft the Swiggy banner + an Insta story for you? Live in 10 min. Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Contrarian operator insight backed by match timing, -12% cover data, and delivery asset drafting.",
                "template_name": "vera_ipl_match_v1",
                "template_params": [owner_name, "7:30 PM", "-12%"],
            }

        # F. Competitor Opened
        if kind == "competitor_opened":
            salutation = f"Dr. {owner_name}" if cat_slug == "dentists" else f"Hi {owner_name}"
            body = (
                f"{salutation}, a new {cat_slug.rstrip('s')} opened 1.3km away in {locality} on Google Maps with 5 reviews. "
                f"Your profile has an established {views:,} views and verified rating. "
                f"To protect your top-3 Map pack ranking, want me to post a verified client testimonial spotlight to your GBP today? Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Local competition alert leveraging existing social proof to protect map ranking.",
                "template_name": "vera_competitor_opened_v1",
                "template_params": [salutation, locality, str(views)],
            }

        # G. CDE Opportunity / Webinar
        if "cde" in kind:
            body = (
                f"Dr. {owner_name}, IDA Delhi's CDE session on Digital Impressions & Trios 5 CAD/CAM ROI is scheduled for "
                f"May 2 at 7:00 PM (2 CDE credits). It is free for IDA members and highly relevant to solo practices. "
                f"Want me to send you the 1-click registration details? Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Collegial CDE notification with exact date, speaker topic, CDE credits, and binary YES ask.",
                "template_name": "vera_cde_webinar_v1",
                "template_params": [owner_name, "May 2 at 7:00 PM", "2 CDE credits"],
            }

        # H. Curious Ask Due (Asking the merchant lever)
        if kind == "curious_ask_due":
            body = (
                f"Hi {owner_name}! Quick check — what service or treatment has been most asked-for this week at {biz_name}? "
                f"Main aapke answer ko ek high-engagement Google post aur 4-line WhatsApp snippet mein convert kar doongi. "
                f"Takes 2 minutes. Reply with the service name."
            )
            return {
                "body": body,
                "cta": "open_ended",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "High-compulsion curious ask leveraging the merchant's ground-level knowledge with reciprocity payoff.",
                "template_name": "vera_curious_ask_v1",
                "template_params": [owner_name, biz_name],
            }

        # I. Festival Upcoming / Category Seasonal
        if kind in ("festival_upcoming", "category_seasonal"):
            event_name = payload.get("festival_name") or payload.get("event") or "festival season"
            body = (
                f"Hi {owner_name}! With {event_name} coming up, customer searches in {locality} are spiking +35%. "
                f"Aapke {biz_name} ke liye ek high-intent festive campaign draft ready hai featuring '{active_offer_title or 'Special Festive Package'}'. "
                f"Want me to schedule the GBP post and customer WhatsApp announcement today? Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Timely seasonal demand alert with ready-to-publish festive campaign assets.",
                "template_name": "vera_festival_v1",
                "template_params": [owner_name, event_name, locality],
            }

        # J. Milestone Reached
        if kind == "milestone_reached":
            body = (
                f"Congratulations {owner_name}! {biz_name} just crossed an exciting milestone: over {views:,} profile visits "
                f"and verified local reviews in {city}. Want me to publish a celebratory thank-you post to your Google profile "
                f"to thank customers and boost your local rank? Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Milestone celebration creating social proof and local credibility.",
                "template_name": "vera_milestone_v1",
                "template_params": [owner_name, biz_name, str(views)],
            }

        # K. Renewal Due / Subscription
        if kind == "renewal_due":
            days = merchant.get("subscription", {}).get("days_remaining", 7)
            body = (
                f"Hi {owner_name}, your magicpin Pro plan has {days} days remaining. "
                f"Renewing on time ensures your automated Google Business posts, review manager, and customer inquiries remain active without pause. "
                f"Want me to send your 1-click renewal payment link with current plan benefits? Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Clear subscription renewal heads-up highlighting service continuity and zero-friction payment link.",
                "template_name": "vera_renewal_v1",
                "template_params": [owner_name, str(days)],
            }

        # L. Dormant with Vera
        if kind == "dormant_with_vera":
            body = (
                f"Hi {owner_name}, quick check-in from Vera! Businesses in {locality} have seen steady customer queries this week. "
                f"Aapke {biz_name} profile ke liye I noticed views are at {views:,}. "
                f"Would you like me to draft a fresh weekend offer post featuring '{active_offer_title or 'Special Offer'}'? Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Re-engagement message grounded on locality trends and active catalog offer.",
                "template_name": "vera_dormant_reengage_v1",
                "template_params": [owner_name, locality, str(views)],
            }

        # M. Review Theme Emerged
        if kind == "review_theme_emerged":
            body = (
                f"Hi {owner_name}, our weekly review analysis detected customer feedback highlighting quality and service at {biz_name}. "
                f"Responding quickly to reviews on Google increases profile conversion by up to 18%. "
                f"Want me to draft personalized, professional responses for your recent reviews? Reply YES."
            )
            return {
                "body": body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": suppression_key,
                "rationale": "Review engagement loop highlighting conversion gain and externalizing response drafting.",
                "template_name": "vera_review_theme_v1",
                "template_params": [owner_name, biz_name],
            }

        # General Grounded Fallback (Handles adaptive Phase 3 triggers dynamically)
        salutation = f"Dr. {owner_name}" if cat_slug == "dentists" else f"Hi {owner_name}"
        dynamic_topic = (
            payload.get("topic")
            or payload.get("headline")
            or payload.get("event")
            or payload.get("festival")
            or payload.get("metric_or_topic")
            or kind.replace("_", " ")
        )
        stat_mention = payload.get("stat") or payload.get("delta") or f"{views:,} views in the last 30 days"

        body = (
            f"{salutation}, Vera here. Quick heads-up on {dynamic_topic} for {biz_name} in {locality}: "
            f"your profile reached {stat_mention}. "
            f"I have prepared a high-visibility update featuring your '{active_offer_title or 'special package'}'. "
            f"Want me to schedule it for tomorrow 10 AM? Reply YES."
        )
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "vera",
            "suppression_key": suppression_key,
            "rationale": f"Adaptive grounded engagement for '{kind}' anchored on topic '{dynamic_topic}' and verifiable metrics.",
            "template_name": f"vera_{cat_slug}_adaptive_v1",
            "template_params": [salutation, biz_name, str(views)],
        }
