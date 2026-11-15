-- 0018_contact_lines.sql : who answers a published number (founder, 15 Nov 2026)
--
-- "Most of them are not personal numbers, they are automation numbers." Of the first 33 India and UAE leads,
-- nearly every number was the clinic's front-desk WhatsApp (the green chat button, a booking or emergency line,
-- the site-wide header number), answered by an auto-reply and then a receptionist, never the owner. Each contact
-- now says who answers it:
--   owner       the owner, founder or doctor in charge: a number or address the page ties to that person
--   front_desk  reception, booking, enquiries, the WhatsApp button, the site-wide number, info@ style addresses
--   bot         a WhatsApp API vendor's line, a toll-free or helpline number, a number other businesses also
--               publish (a call centre or agency), or a number registered in another country
--   other       a business mobile or address with nothing that says who answers
-- line_why is the reason in plain words, shown in the app next to the number.
-- The primary contact (what the app, the email and the sheets show) now puts the owner first and bots last.

alter table public.contacts
  add column if not exists line text not null default 'other'
    constraint contacts_line_known check (line in ('owner', 'front_desk', 'bot', 'other')),
  add column if not exists line_why text;

create or replace view public.v_primary_contact with (security_invoker = true) as
select distinct on (c.business_id)
  c.business_id, c.id as contact_id, c.name, c.role, c.phone_e164, c.phone_type,
  c.email, c.source, c.source_url, c.is_decision_maker, c.verified, c.line, c.line_why
from public.contacts c
where not c.do_not_contact
  and (c.phone_e164 is not null or c.email is not null)
  and not exists (select 1 from public.suppression su where su.phone_e164 = c.phone_e164)
  and not exists (select 1 from public.suppression su where lower(su.email) = lower(c.email))
order by c.business_id,
         case
           when c.line = 'owner' and c.phone_e164 is not null then 0
           when c.line = 'owner' then 1
           when c.line = 'other' and c.phone_type = 'mobile' then 2
           when c.line = 'front_desk' and c.phone_e164 is not null then 3
           when c.line <> 'bot' and c.email is not null then 4
           when c.line <> 'bot' then 5
           else 6
         end,
         c.verified desc,
         (c.source = 'website') desc,
         c.created_at;
