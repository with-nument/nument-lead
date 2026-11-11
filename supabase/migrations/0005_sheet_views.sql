-- 0005_sheet_views.sql : the read model for the Google Sheet sync (Step 13.3.2)
--
-- A lead appears on both sheets when it is graded A or B and still open, or once anyone has worked on it
-- (any stage other than new), so it never disappears mid-conversation.
-- Contact and top signal come from v_primary_contact and v_top_signal (0002), so the sheet shows the same
-- number and the same reason as the app, and never a suppressed contact.
-- Has deal_value_inr for the master sheet: engine only (A.13.5 rule 2, 2.8.4 rule 3). No grant to app users.

create or replace view public.v_sheet_leads with (security_invoker = true) as
select
  l.id                 as lead_id,
  l.grade, l.stage, l.pitch_mode, l.test_group, l.angle,
  l.message, l.message_alt, l.followup_d3, l.followup_d7,
  l.wa_at, l.call_at, l.d3_at, l.d7_at, l.meeting_at,
  l.next_step, l.due_at, l.deal_value_inr, l.notes,
  l.updated_at         as lead_updated_at,
  b.id                 as business_id,
  b.name, b.city, b.country, b.website, b.segment_id,
  s.total              as score_total, s.judge_note, s.reasons,
  pc.name              as contact_name, pc.role as contact_role,
  pc.phone_e164, pc.phone_type, pc.email, pc.source as phone_source,
  ts.type              as top_signal_type, ts.quote as top_signal_quote,
  ts.url               as top_signal_url, ts.observed_at as top_signal_at
from public.leads l
join public.businesses b on b.id = l.business_id
left join public.scores s on s.id = l.score_id
left join public.v_primary_contact pc on pc.business_id = b.id
left join public.v_top_signal ts on ts.business_id = b.id
where (l.grade in ('A','B') and l.stage not in
        ('won','retainer','lost','not_now','not_a_fit','wrong_contact'))
   or l.stage <> 'new';
