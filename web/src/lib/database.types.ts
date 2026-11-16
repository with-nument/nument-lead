// Database types for the public schema.
// Generated: run `pnpm db:types` (needs SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF) after every migration.
// Do not edit by hand. (16 Nov 2026: migrations 0019 to 0028 and 0033 were added from a migrated local Postgres in the
// same format; the next `pnpm db:types` replaces this with the live schema.)

export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.18"
  }
  public: {
    Tables: {
      activities: {
        Row: {
          at: string
          id: string
          lead_id: string
          payload: Json
          source: string
          type: string
          user_id: string | null
        }
        Insert: {
          at?: string
          id?: string
          lead_id: string
          payload?: Json
          source: string
          type: string
          user_id?: string | null
        }
        Update: {
          at?: string
          id?: string
          lead_id?: string
          payload?: Json
          source?: string
          type?: string
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_followups_due"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_funnel"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_lead_funnel"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_leads_admin"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_leads_caller"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_pipeline"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "activities_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_today"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "activities_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
        ]
      }
      businesses: {
        Row: {
          address: string | null
          branches_count: number | null
          category: string | null
          city: string | null
          country: string
          created_at: string
          extra: Json
          first_seen_at: string
          id: string
          last_seen_at: string
          lat: number | null
          lng: number | null
          locality: string | null
          name: string
          norm_name: string
          overture_id: string | null
          place_id: string | null
          places_fetched_at: string | null
          queue_priority: number | null
          queued_at: string | null
          rating: number | null
          reject_reason: string | null
          researched_at: string | null
          review_count: number | null
          segment_id: string
          staff_count: number | null
          status: string
          subcategory: string | null
          updated_at: string
          web_domain: string | null
          website: string | null
        }
        Insert: {
          address?: string | null
          branches_count?: number | null
          category?: string | null
          city?: string | null
          country: string
          created_at?: string
          extra?: Json
          first_seen_at?: string
          id?: string
          last_seen_at?: string
          lat?: number | null
          lng?: number | null
          locality?: string | null
          name: string
          norm_name: string
          overture_id?: string | null
          place_id?: string | null
          places_fetched_at?: string | null
          queue_priority?: number | null
          queued_at?: string | null
          rating?: number | null
          reject_reason?: string | null
          researched_at?: string | null
          review_count?: number | null
          segment_id: string
          staff_count?: number | null
          status?: string
          subcategory?: string | null
          updated_at?: string
          web_domain?: string | null
          website?: string | null
        }
        Update: {
          address?: string | null
          branches_count?: number | null
          category?: string | null
          city?: string | null
          country?: string
          created_at?: string
          extra?: Json
          first_seen_at?: string
          id?: string
          last_seen_at?: string
          lat?: number | null
          lng?: number | null
          locality?: string | null
          name?: string
          norm_name?: string
          overture_id?: string | null
          place_id?: string | null
          places_fetched_at?: string | null
          queue_priority?: number | null
          queued_at?: string | null
          rating?: number | null
          reject_reason?: string | null
          researched_at?: string | null
          review_count?: number | null
          segment_id?: string
          staff_count?: number | null
          status?: string
          subcategory?: string | null
          updated_at?: string
          web_domain?: string | null
          website?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "businesses_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      case_studies: {
        Row: {
          body: Json
          client: string | null
          created_at: string
          id: string
          offer_key: string | null
          published: boolean
          slug: string
          summary: string
          title: string
        }
        Insert: {
          body?: Json
          client?: string | null
          created_at?: string
          id?: string
          offer_key?: string | null
          published?: boolean
          slug: string
          summary: string
          title: string
        }
        Update: {
          body?: Json
          client?: string | null
          created_at?: string
          id?: string
          offer_key?: string | null
          published?: boolean
          slug?: string
          summary?: string
          title?: string
        }
        Relationships: [
          {
            foreignKeyName: "case_studies_offer_key_fkey"
            columns: ["offer_key"]
            isOneToOne: false
            referencedRelation: "offers"
            referencedColumns: ["key"]
          },
        ]
      }
      contacts: {
        Row: {
          business_id: string
          created_at: string
          do_not_contact: boolean
          email: string | null
          email_checked_at: string | null
          email_origin: string | null
          email_pattern: string | null
          email_status: string
          id: string
          is_decision_maker: boolean
          line: string
          line_why: string | null
          name: string | null
          phone_e164: string | null
          phone_type: string
          quote: string | null
          role: string | null
          source: string
          source_url: string | null
          updated_at: string
          verified: boolean
          verified_at: string | null
        }
        Insert: {
          business_id: string
          created_at?: string
          do_not_contact?: boolean
          email?: string | null
          id?: string
          is_decision_maker?: boolean
          line?: string
          line_why?: string | null
          name?: string | null
          phone_e164?: string | null
          phone_type?: string
          quote?: string | null
          role?: string | null
          source: string
          source_url?: string | null
          updated_at?: string
          verified?: boolean
          verified_at?: string | null
        }
        Update: {
          business_id?: string
          created_at?: string
          do_not_contact?: boolean
          email?: string | null
          id?: string
          is_decision_maker?: boolean
          line?: string
          line_why?: string | null
          name?: string | null
          phone_e164?: string | null
          phone_type?: string
          quote?: string | null
          role?: string | null
          source?: string
          source_url?: string | null
          updated_at?: string
          verified?: boolean
          verified_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "contacts_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "contacts_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
        ]
      }
      costs: {
        Row: {
          at: string
          calls: number
          fallback_from: string | null
          id: string
          input_tokens: number
          inr: number
          model: string | null
          output_tokens: number
          provider: string
          run_id: string | null
          task: string
          usd: number
        }
        Insert: {
          at?: string
          calls?: number
          fallback_from?: string | null
          id?: string
          input_tokens?: number
          inr?: number
          model?: string | null
          output_tokens?: number
          provider: string
          run_id?: string | null
          task: string
          usd?: number
        }
        Update: {
          at?: string
          calls?: number
          fallback_from?: string | null
          id?: string
          input_tokens?: number
          inr?: number
          model?: string | null
          output_tokens?: number
          provider?: string
          run_id?: string | null
          task?: string
          usd?: number
        }
        Relationships: [
          {
            foreignKeyName: "costs_run_id_fkey"
            columns: ["run_id"]
            isOneToOne: false
            referencedRelation: "runs"
            referencedColumns: ["id"]
          },
        ]
      }
      custom_queries: {
        Row: {
          created_at: string
          created_by: string | null
          id: string
          query: string
          segment_id: string
          status: string
        }
        Insert: {
          created_at?: string
          created_by?: string | null
          id?: string
          query: string
          segment_id: string
          status?: string
        }
        Update: {
          created_at?: string
          created_by?: string | null
          id?: string
          query?: string
          segment_id?: string
          status?: string
        }
        Relationships: [
          {
            foreignKeyName: "custom_queries_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
          {
            foreignKeyName: "custom_queries_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      email_checks: {
        Row: {
          checked_at: string
          email: string
          provider: string
          raw: Json
          result: string
        }
        Insert: {
          checked_at?: string
          email: string
          provider: string
          raw?: Json
          result: string
        }
        Update: {
          checked_at?: string
          email?: string
          provider?: string
          raw?: Json
          result?: string
        }
        Relationships: []
      }
      email_domains: {
        Row: {
          catch_all: boolean | null
          checked_at: string
          domain: string
          mx_provider: string | null
        }
        Insert: {
          catch_all?: boolean | null
          checked_at?: string
          domain: string
          mx_provider?: string | null
        }
        Update: {
          catch_all?: boolean | null
          checked_at?: string
          domain?: string
          mx_provider?: string | null
        }
        Relationships: []
      }
      email_messages: {
        Row: {
          body: string | null
          classification: string | null
          classification_confidence: number | null
          created_at: string
          direction: string
          error: string | null
          gmail_message_id: string | null
          id: string
          rfc_message_id: string | null
          scheduled_for: string | null
          sent_at: string | null
          status: string
          step: number | null
          subject: string | null
          suggested_reply: string | null
          thread_id: string
          updated_at: string
        }
        Insert: {
          body?: string | null
          classification?: string | null
          classification_confidence?: number | null
          created_at?: string
          direction: string
          error?: string | null
          gmail_message_id?: string | null
          id?: string
          rfc_message_id?: string | null
          scheduled_for?: string | null
          sent_at?: string | null
          status: string
          step?: number | null
          subject?: string | null
          suggested_reply?: string | null
          thread_id: string
          updated_at?: string
        }
        Update: {
          body?: string | null
          classification?: string | null
          classification_confidence?: number | null
          created_at?: string
          direction?: string
          error?: string | null
          gmail_message_id?: string | null
          id?: string
          rfc_message_id?: string | null
          scheduled_for?: string | null
          sent_at?: string | null
          status?: string
          step?: number | null
          subject?: string | null
          suggested_reply?: string | null
          thread_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "email_messages_thread_id_fkey"
            columns: ["thread_id"]
            isOneToOne: false
            referencedRelation: "email_threads"
            referencedColumns: ["id"]
          },
        ]
      }
      email_threads: {
        Row: {
          contact_id: string | null
          created_at: string
          gmail_thread_id: string | null
          id: string
          lead_id: string
          mailbox_id: string | null
          mode: string
          paused_until: string | null
          status: string
          stop_reason: string | null
          to_domain: string
          to_email: string
          updated_at: string
        }
        Insert: {
          contact_id?: string | null
          created_at?: string
          gmail_thread_id?: string | null
          id?: string
          lead_id: string
          mailbox_id?: string | null
          mode?: string
          paused_until?: string | null
          status?: string
          stop_reason?: string | null
          to_domain: string
          to_email: string
          updated_at?: string
        }
        Update: {
          contact_id?: string | null
          created_at?: string
          gmail_thread_id?: string | null
          id?: string
          lead_id?: string
          mailbox_id?: string | null
          mode?: string
          paused_until?: string | null
          status?: string
          stop_reason?: string | null
          to_domain?: string
          to_email?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "email_threads_contact_id_fkey"
            columns: ["contact_id"]
            isOneToOne: false
            referencedRelation: "contacts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "email_threads_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: true
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "email_threads_mailbox_id_fkey"
            columns: ["mailbox_id"]
            isOneToOne: false
            referencedRelation: "mailboxes"
            referencedColumns: ["id"]
          },
        ]
      }
      facts: {
        Row: {
          business_id: string
          created_at: string
          field: string
          id: string
          model: string | null
          page_id: string | null
          quote: string | null
          url: string | null
          value: Json
          verified: boolean
          verified_at: string | null
          verify_score: number | null
        }
        Insert: {
          business_id: string
          created_at?: string
          field: string
          id?: string
          model?: string | null
          page_id?: string | null
          quote?: string | null
          url?: string | null
          value: Json
          verified?: boolean
          verified_at?: string | null
          verify_score?: number | null
        }
        Update: {
          business_id?: string
          created_at?: string
          field?: string
          id?: string
          model?: string | null
          page_id?: string | null
          quote?: string | null
          url?: string | null
          value?: Json
          verified?: boolean
          verified_at?: string | null
          verify_score?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "facts_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "facts_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
          {
            foreignKeyName: "facts_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "pages"
            referencedColumns: ["id"]
          },
        ]
      }
      feedback: {
        Row: {
          at: string
          id: string
          lead_id: string
          rating: number
          reason: string | null
          user_id: string | null
        }
        Insert: {
          at?: string
          id?: string
          lead_id: string
          rating: number
          reason?: string | null
          user_id?: string | null
        }
        Update: {
          at?: string
          id?: string
          lead_id?: string
          rating?: number
          reason?: string | null
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_followups_due"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_funnel"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_lead_funnel"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_leads_admin"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_leads_caller"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_pipeline"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "feedback_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_today"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "feedback_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
        ]
      }
      golden_labels: {
        Row: {
          at: string
          business_id: string
          id: string
          label: string
          labeled_by: string | null
          reasons: string | null
        }
        Insert: {
          at?: string
          business_id: string
          id?: string
          label: string
          labeled_by?: string | null
          reasons?: string | null
        }
        Update: {
          at?: string
          business_id?: string
          id?: string
          label?: string
          labeled_by?: string | null
          reasons?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "golden_labels_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "golden_labels_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
          {
            foreignKeyName: "golden_labels_labeled_by_fkey"
            columns: ["labeled_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
        ]
      }
      inbox_posts: {
        Row: {
          created_at: string
          created_by: string | null
          id: string
          lead_id: string | null
          segment_id: string | null
          status: string
          text: string
          url: string | null
        }
        Insert: {
          created_at?: string
          created_by?: string | null
          id?: string
          lead_id?: string | null
          segment_id?: string | null
          status?: string
          text: string
          url?: string | null
        }
        Update: {
          created_at?: string
          created_by?: string | null
          id?: string
          lead_id?: string | null
          segment_id?: string | null
          status?: string
          text?: string
          url?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "inbox_posts_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_followups_due"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_funnel"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_lead_funnel"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_leads_admin"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_leads_caller"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_pipeline"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "inbox_posts_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_today"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "inbox_posts_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      lead_offers: {
        Row: {
          cited_ids: string[]
          created_at: string
          lead_id: string
          model: string | null
          offer_key: string
          rank: number
          why_now: string | null
        }
        Insert: {
          cited_ids?: string[]
          created_at?: string
          lead_id: string
          model?: string | null
          offer_key: string
          rank: number
          why_now?: string | null
        }
        Update: {
          cited_ids?: string[]
          created_at?: string
          lead_id?: string
          model?: string | null
          offer_key?: string
          rank?: number
          why_now?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "lead_offers_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "lead_offers_offer_key_fkey"
            columns: ["offer_key"]
            isOneToOne: false
            referencedRelation: "offers"
            referencedColumns: ["key"]
          },
        ]
      }
      leads: {
        Row: {
          angle: string | null
          business_id: string
          call_at: string | null
          channel: string
          created_at: string
          d3_at: string | null
          d7_at: string | null
          deal_currency: string
          deal_value_inr: number | null
          due_at: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string
          id: string
          last_activity_at: string
          lost_reason: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          message_check_score: number | null
          message_model: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          pitch_mode: string
          regen_requested_at: string | null
          retainer_monthly_value: number | null
          score_id: string | null
          segment_id: string
          skipped_until: string | null
          stage: string
          test_group: string | null
          updated_at: string
          wa_at: string | null
        }
        Insert: {
          angle?: string | null
          business_id: string
          call_at?: string | null
          channel?: string
          created_at?: string
          d3_at?: string | null
          d7_at?: string | null
          deal_currency?: string
          deal_value_inr?: number | null
          due_at?: string | null
          email_body?: string | null
          email_subject?: string | null
          followup_d3?: string | null
          followup_d7?: string | null
          grade: string
          id?: string
          last_activity_at?: string
          lost_reason?: string | null
          meeting_at?: string | null
          message?: string | null
          message_alt?: string | null
          message_check_score?: number | null
          message_model?: string | null
          next_step?: string | null
          notes?: string | null
          owner_id?: string | null
          pitch_mode: string
          regen_requested_at?: string | null
          retainer_monthly_value?: number | null
          score_id?: string | null
          segment_id: string
          skipped_until?: string | null
          stage?: string
          test_group?: string | null
          updated_at?: string
          wa_at?: string | null
        }
        Update: {
          angle?: string | null
          business_id?: string
          call_at?: string | null
          channel?: string
          created_at?: string
          d3_at?: string | null
          d7_at?: string | null
          deal_currency?: string
          deal_value_inr?: number | null
          due_at?: string | null
          email_body?: string | null
          email_subject?: string | null
          followup_d3?: string | null
          followup_d7?: string | null
          grade?: string
          id?: string
          last_activity_at?: string
          lost_reason?: string | null
          meeting_at?: string | null
          message?: string | null
          message_alt?: string | null
          message_check_score?: number | null
          message_model?: string | null
          next_step?: string | null
          notes?: string | null
          owner_id?: string | null
          pitch_mode?: string
          regen_requested_at?: string | null
          retainer_monthly_value?: number | null
          score_id?: string | null
          segment_id?: string
          skipped_until?: string | null
          stage?: string
          test_group?: string | null
          updated_at?: string
          wa_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
          {
            foreignKeyName: "leads_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
          {
            foreignKeyName: "leads_score_id_fkey"
            columns: ["score_id"]
            isOneToOne: false
            referencedRelation: "scores"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      llm_batch_reservations: {
        Row: {
          created_at: string
          id: number
          llm_batch_id: string | null
          released: boolean
          reserved_inr: number
        }
        Insert: {
          created_at?: string
          id?: number
          llm_batch_id?: string | null
          released?: boolean
          reserved_inr: number
        }
        Update: {
          created_at?: string
          id?: number
          llm_batch_id?: string | null
          released?: boolean
          reserved_inr?: number
        }
        Relationships: [
          {
            foreignKeyName: "llm_batch_reservations_llm_batch_id_fkey"
            columns: ["llm_batch_id"]
            isOneToOne: false
            referencedRelation: "llm_batches"
            referencedColumns: ["id"]
          },
        ]
      }
      llm_batches: {
        Row: {
          completed_at: string | null
          id: string
          item_count: number
          provider: string
          provider_batch_id: string
          result_ref: string | null
          status: string
          submitted_at: string
          task: string
        }
        Insert: {
          completed_at?: string | null
          id?: string
          item_count?: number
          provider: string
          provider_batch_id: string
          result_ref?: string | null
          status?: string
          submitted_at?: string
          task: string
        }
        Update: {
          completed_at?: string | null
          id?: string
          item_count?: number
          provider?: string
          provider_batch_id?: string
          result_ref?: string | null
          status?: string
          submitted_at?: string
          task?: string
        }
        Relationships: []
      }
      llm_cache: {
        Row: {
          created_at: string
          expires_at: string
          key: string
          model: string
          response: Json
          task: string
        }
        Insert: {
          created_at?: string
          expires_at: string
          key: string
          model: string
          response: Json
          task: string
        }
        Update: {
          created_at?: string
          expires_at?: string
          key?: string
          model?: string
          response?: Json
          task?: string
        }
        Relationships: []
      }
      mailboxes: {
        Row: {
          connected_at: string | null
          display_name: string
          email: string
          id: string
          last_error: string | null
          paused_reason: string | null
          provider: string
          sent_day: string | null
          sent_today: number
          status: string
          updated_at: string
          warmup_started_on: string | null
        }
        Insert: {
          connected_at?: string | null
          display_name?: string
          email: string
          id?: string
          last_error?: string | null
          paused_reason?: string | null
          provider?: string
          sent_day?: string | null
          sent_today?: number
          status?: string
          updated_at?: string
          warmup_started_on?: string | null
        }
        Update: {
          connected_at?: string | null
          display_name?: string
          email?: string
          id?: string
          last_error?: string | null
          paused_reason?: string | null
          provider?: string
          sent_day?: string | null
          sent_today?: number
          status?: string
          updated_at?: string
          warmup_started_on?: string | null
        }
        Relationships: []
      }
      notify_recipients: {
        Row: {
          active: boolean
          alerts: boolean
          created_at: string
          created_by: string | null
          email: string
          id: string
          morning: boolean
          name: string | null
          weekly: boolean
        }
        Insert: {
          active?: boolean
          alerts?: boolean
          created_at?: string
          created_by?: string | null
          email: string
          id?: string
          morning?: boolean
          name?: string | null
          weekly?: boolean
        }
        Update: {
          active?: boolean
          alerts?: boolean
          created_at?: string
          created_by?: string | null
          email?: string
          id?: string
          morning?: boolean
          name?: string | null
          weekly?: boolean
        }
        Relationships: [
          {
            foreignKeyName: "notify_recipients_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
        ]
      }
      offers: {
        Row: {
          active: boolean
          best_for: string
          key: string
          name: string
          promise: string
          sort: number
          timeline: string
          typical_range: Json
        }
        Insert: {
          active?: boolean
          best_for: string
          key: string
          name: string
          promise: string
          sort?: number
          timeline: string
          typical_range?: Json
        }
        Update: {
          active?: boolean
          best_for?: string
          key?: string
          name?: string
          promise?: string
          sort?: number
          timeline?: string
          typical_range?: Json
        }
        Relationships: []
      }
      pages: {
        Row: {
          business_id: string | null
          fetched_at: string
          http_status: number | null
          id: string
          render_mode: string
          robots_allowed: boolean
          text: string | null
          text_hash: string | null
          title: string | null
          url: string
        }
        Insert: {
          business_id?: string | null
          fetched_at?: string
          http_status?: number | null
          id?: string
          render_mode?: string
          robots_allowed?: boolean
          text?: string | null
          text_hash?: string | null
          title?: string | null
          url: string
        }
        Update: {
          business_id?: string | null
          fetched_at?: string
          http_status?: number | null
          id?: string
          render_mode?: string
          robots_allowed?: boolean
          text?: string | null
          text_hash?: string | null
          title?: string | null
          url?: string
        }
        Relationships: [
          {
            foreignKeyName: "pages_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "pages_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
        ]
      }
      plan_pages: {
        Row: {
          content: Json
          created_at: string
          expires_at: string
          first_viewed_at: string | null
          kind: string
          last_viewed_at: string | null
          lead_id: string
          status: string
          token: string
          views: number
        }
        Insert: {
          content: Json
          created_at?: string
          expires_at?: string
          first_viewed_at?: string | null
          kind?: string
          last_viewed_at?: string | null
          lead_id: string
          status?: string
          token: string
          views?: number
        }
        Update: {
          content?: Json
          created_at?: string
          expires_at?: string
          first_viewed_at?: string | null
          kind?: string
          last_viewed_at?: string | null
          lead_id?: string
          status?: string
          token?: string
          views?: number
        }
        Relationships: [
          {
            foreignKeyName: "plan_pages_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          created_at: string
          full_name: string | null
          role: string
          user_id: string
        }
        Insert: {
          created_at?: string
          full_name?: string | null
          role?: string
          user_id: string
        }
        Update: {
          created_at?: string
          full_name?: string | null
          role?: string
          user_id?: string
        }
        Relationships: []
      }
      proposals: {
        Row: {
          call_notes: string | null
          content: Json
          created_at: string
          id: string
          lead_id: string
          model: string | null
          plan_token: string | null
          status: string
          updated_at: string
        }
        Insert: {
          call_notes?: string | null
          content?: Json
          created_at?: string
          id?: string
          lead_id: string
          model?: string | null
          plan_token?: string | null
          status?: string
          updated_at?: string
        }
        Update: {
          call_notes?: string | null
          content?: Json
          created_at?: string
          id?: string
          lead_id?: string
          model?: string | null
          plan_token?: string | null
          status?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "proposals_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "proposals_plan_token_fkey"
            columns: ["plan_token"]
            isOneToOne: false
            referencedRelation: "plan_pages"
            referencedColumns: ["token"]
          },
        ]
      }
      reports: {
        Row: {
          content: Json
          created_at: string
          id: number
          kind: string
          markdown: string
          period_end: string | null
          period_start: string | null
        }
        Insert: {
          content: Json
          created_at?: string
          id?: number
          kind: string
          markdown: string
          period_end?: string | null
          period_start?: string | null
        }
        Update: {
          content?: Json
          created_at?: string
          id?: number
          kind?: string
          markdown?: string
          period_end?: string | null
          period_start?: string | null
        }
        Relationships: []
      }
      runs: {
        Row: {
          error: string | null
          finished_at: string | null
          id: string
          kind: string
          started_at: string
          stats: Json
          status: string
        }
        Insert: {
          error?: string | null
          finished_at?: string | null
          id?: string
          kind: string
          started_at?: string
          stats?: Json
          status?: string
        }
        Update: {
          error?: string | null
          finished_at?: string | null
          id?: string
          kind?: string
          started_at?: string
          stats?: Json
          status?: string
        }
        Relationships: []
      }
      saved_views: {
        Row: {
          created_at: string
          id: string
          name: string
          query: Json
          shared: boolean
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          name: string
          query?: Json
          shared?: boolean
          user_id?: string
        }
        Update: {
          created_at?: string
          id?: string
          name?: string
          query?: Json
          shared?: boolean
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "saved_views_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
        ]
      }
      scores: {
        Row: {
          business_id: string
          can_pay: number
          computed_at: string
          fit: number
          grade: string
          id: string
          intent: number
          judge_grade: string | null
          judge_model: string | null
          judge_note: string | null
          pitch_mode: string
          reach: number
          reasons: Json
          total: number
          version: string
        }
        Insert: {
          business_id: string
          can_pay?: number
          computed_at?: string
          fit: number
          grade: string
          id?: string
          intent?: number
          judge_grade?: string | null
          judge_model?: string | null
          judge_note?: string | null
          pitch_mode: string
          reach?: number
          reasons?: Json
          total: number
          version: string
        }
        Update: {
          business_id?: string
          can_pay?: number
          computed_at?: string
          fit?: number
          grade?: string
          id?: string
          intent?: number
          judge_grade?: string | null
          judge_model?: string | null
          judge_note?: string | null
          pitch_mode?: string
          reach?: number
          reasons?: Json
          total?: number
          version?: string
        }
        Relationships: [
          {
            foreignKeyName: "scores_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "scores_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
        ]
      }
      segments: {
        Row: {
          config: Json
          config_version: string | null
          country: string
          created_at: string
          daily_quota: number
          display_name: string
          domain: string
          enabled: boolean
          id: string
          updated_at: string
        }
        Insert: {
          config?: Json
          config_version?: string | null
          country: string
          created_at?: string
          daily_quota?: number
          display_name: string
          domain: string
          enabled?: boolean
          id: string
          updated_at?: string
        }
        Update: {
          config?: Json
          config_version?: string | null
          country?: string
          created_at?: string
          daily_quota?: number
          display_name?: string
          domain?: string
          enabled?: boolean
          id?: string
          updated_at?: string
        }
        Relationships: []
      }
      settings: {
        Row: {
          key: string
          updated_at: string
          value: Json
        }
        Insert: {
          key: string
          updated_at?: string
          value: Json
        }
        Update: {
          key?: string
          updated_at?: string
          value?: Json
        }
        Relationships: []
      }
      sheet_snapshots: {
        Row: {
          lead_id: string
          sheet: string
          values: Json
          written_at: string
        }
        Insert: {
          lead_id: string
          sheet: string
          values: Json
          written_at?: string
        }
        Update: {
          lead_id?: string
          sheet?: string
          values?: Json
          written_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_followups_due"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_funnel"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_lead_funnel"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_leads_admin"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_leads_caller"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_pipeline"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["lead_id"]
          },
          {
            foreignKeyName: "sheet_snapshots_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "v_today"
            referencedColumns: ["lead_id"]
          },
        ]
      }
      signals: {
        Row: {
          business_id: string
          category: string
          created_at: string
          dedupe_key: string
          details: Json
          expires_at: string
          id: string
          observed_at: string
          points: number
          quote: string | null
          source: string
          type: string
          url: string | null
        }
        Insert: {
          business_id: string
          category: string
          created_at?: string
          dedupe_key: string
          details?: Json
          expires_at: string
          id?: string
          observed_at: string
          points?: number
          quote?: string | null
          source: string
          type: string
          url?: string | null
        }
        Update: {
          business_id?: string
          category?: string
          created_at?: string
          dedupe_key?: string
          details?: Json
          expires_at?: string
          id?: string
          observed_at?: string
          points?: number
          quote?: string | null
          source?: string
          type?: string
          url?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "signals_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "signals_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
        ]
      }
      source_health: {
        Row: {
          blocked_until: string | null
          enabled: boolean
          last_error: string | null
          last_error_at: string | null
          last_ok_at: string | null
          recent_blocks: string[]
          requests_day: string
          requests_today: number
          source: string
        }
        Insert: {
          blocked_until?: string | null
          enabled?: boolean
          last_error?: string | null
          last_error_at?: string | null
          last_ok_at?: string | null
          recent_blocks?: string[]
          requests_day?: string
          requests_today?: number
          source: string
        }
        Update: {
          blocked_until?: string | null
          enabled?: boolean
          last_error?: string | null
          last_error_at?: string | null
          last_ok_at?: string | null
          recent_blocks?: string[]
          requests_day?: string
          requests_today?: number
          source?: string
        }
        Relationships: []
      }
      source_records: {
        Row: {
          business_id: string | null
          fetched_at: string
          id: string
          payload: Json
          source: string
          source_key: string
        }
        Insert: {
          business_id?: string | null
          fetched_at?: string
          id?: string
          payload?: Json
          source: string
          source_key: string
        }
        Update: {
          business_id?: string | null
          fetched_at?: string
          id?: string
          payload?: Json
          source?: string
          source_key?: string
        }
        Relationships: [
          {
            foreignKeyName: "source_records_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "source_records_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
        ]
      }
      startup_profiles: {
        Row: {
          business_id: string
          can_pay: string
          can_pay_evidence: string[]
          checked_at: string | null
          domain_created_at: string | null
          evidence: Json
          first_seen_at: string | null
          funding_at: string | null
          funding_round: string | null
          funding_usd: number | null
          is_startup: boolean | null
          is_startup_why: string | null
          no_code_platform: string | null
          product_status: string
          team_size: number | null
          team_size_evidence: string[]
          team_size_source: string | null
          tech_team: string
          tech_team_evidence: string[]
          updated_at: string
          uses_ai: boolean | null
        }
        Insert: {
          business_id: string
          can_pay?: string
          can_pay_evidence?: string[]
          checked_at?: string | null
          domain_created_at?: string | null
          evidence?: Json
          first_seen_at?: string | null
          funding_at?: string | null
          funding_round?: string | null
          funding_usd?: number | null
          is_startup?: boolean | null
          is_startup_why?: string | null
          no_code_platform?: string | null
          product_status?: string
          team_size?: number | null
          team_size_evidence?: string[]
          team_size_source?: string | null
          tech_team?: string
          tech_team_evidence?: string[]
          updated_at?: string
          uses_ai?: boolean | null
        }
        Update: {
          business_id?: string
          can_pay?: string
          can_pay_evidence?: string[]
          checked_at?: string | null
          domain_created_at?: string | null
          evidence?: Json
          first_seen_at?: string | null
          funding_at?: string | null
          funding_round?: string | null
          funding_usd?: number | null
          is_startup?: boolean | null
          is_startup_why?: string | null
          no_code_platform?: string | null
          product_status?: string
          team_size?: number | null
          team_size_evidence?: string[]
          team_size_source?: string | null
          tech_team?: string
          tech_team_evidence?: string[]
          updated_at?: string
          uses_ai?: boolean | null
        }
        Relationships: [
          {
            foreignKeyName: "startup_profiles_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: true
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
        ]
      }
      suppression: {
        Row: {
          added_at: string
          added_by: string | null
          email: string | null
          id: string
          phone_e164: string | null
          reason: string
          web_domain: string | null
        }
        Insert: {
          added_at?: string
          added_by?: string | null
          email?: string | null
          id?: string
          phone_e164?: string | null
          reason: string
          web_domain?: string | null
        }
        Update: {
          added_at?: string
          added_by?: string | null
          email?: string | null
          id?: string
          phone_e164?: string | null
          reason?: string
          web_domain?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "suppression_added_by_fkey"
            columns: ["added_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
        ]
      }
      weight_versions: {
        Row: {
          created_at: string
          created_by: string
          diff: Json | null
          id: number
          method: string
          reason: string | null
          version: number
          weights: Json
        }
        Insert: {
          created_at?: string
          created_by?: string
          diff?: Json | null
          id?: number
          method: string
          reason?: string | null
          version: number
          weights: Json
        }
        Update: {
          created_at?: string
          created_by?: string
          diff?: Json | null
          id?: number
          method?: string
          reason?: string | null
          version?: number
          weights?: Json
        }
        Relationships: []
      }
    }
    Views: {
      v_costs_daily: {
        Row: {
          calls: number | null
          day: string | null
          input_tokens: number | null
          inr: number | null
          output_tokens: number | null
          provider: string | null
          task: string | null
          usd: number | null
        }
        Relationships: []
      }
      v_followups_due: {
        Row: {
          company: string | null
          contact_name: string | null
          due_on: string | null
          followup_text: string | null
          grade: string | null
          lead_id: string | null
          phone_e164: string | null
          segment_id: string | null
          which: string | null
        }
        Relationships: [
          {
            foreignKeyName: "leads_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      v_funnel: {
        Row: {
          angle: string | null
          country: string | null
          created_on: string | null
          grade: string | null
          lead_id: string | null
          pitch_mode: string | null
          reached_contacted: boolean | null
          reached_discovery: boolean | null
          reached_proposal: boolean | null
          reached_talking: boolean | null
          reached_won: boolean | null
          segment_id: string | null
          test_group: string | null
          top_signal_type: string | null
        }
        Relationships: [
          {
            foreignKeyName: "leads_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      v_kpis_week: {
        Row: {
          contacted_this_week: number | null
          conversations: number | null
          discovery_calls: number | null
          new_waiting: number | null
          overdue: number | null
          proposals: number | null
          won: number | null
        }
        Relationships: []
      }
      v_lead_funnel: {
        Row: {
          angle: string | null
          contacted_at: string | null
          country: string | null
          grade: string | null
          is_wrong_contact: boolean | null
          lead_id: string | null
          max_rank: number | null
          pitch_mode: string | null
          segment_id: string | null
          stage: string | null
          test_group: string | null
        }
        Relationships: [
          {
            foreignKeyName: "leads_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      v_leads_admin: {
        Row: {
          angle: string | null
          business_id: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          deal_currency: string | null
          deal_value_inr: number | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          id: string | null
          judge_note: string | null
          last_activity_at: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          message_check_score: number | null
          message_model: string | null
          name: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_source: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          retainer_monthly_value: number | null
          score_id: string | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          top_signal_at: string | null
          top_signal_quote: string | null
          top_signal_type: string | null
          top_signal_url: string | null
          total: number | null
          updated_at: string | null
          wa_at: string | null
          web_domain: string | null
          website: string | null
        }
        Relationships: [
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
          {
            foreignKeyName: "leads_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
          {
            foreignKeyName: "leads_score_id_fkey"
            columns: ["score_id"]
            isOneToOne: false
            referencedRelation: "scores"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      v_leads_caller: {
        Row: {
          angle: string | null
          business_id: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          id: string | null
          judge_note: string | null
          last_activity_at: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          message_check_score: number | null
          message_model: string | null
          name: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_source: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          score_id: string | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          top_signal_at: string | null
          top_signal_quote: string | null
          top_signal_type: string | null
          top_signal_url: string | null
          total: number | null
          updated_at: string | null
          wa_at: string | null
          web_domain: string | null
          website: string | null
        }
        Relationships: [
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
          {
            foreignKeyName: "leads_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
          {
            foreignKeyName: "leads_score_id_fkey"
            columns: ["score_id"]
            isOneToOne: false
            referencedRelation: "scores"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      v_pipeline: {
        Row: {
          angle: string | null
          business_id: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          deal_currency: string | null
          deal_value_inr: number | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          id: string | null
          judge_note: string | null
          last_activity_at: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          message_check_score: number | null
          message_model: string | null
          name: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_source: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          retainer_monthly_value: number | null
          score_id: string | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          top_signal_at: string | null
          top_signal_quote: string | null
          top_signal_type: string | null
          top_signal_url: string | null
          total: number | null
          updated_at: string | null
          wa_at: string | null
          web_domain: string | null
          website: string | null
        }
        Relationships: [
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
          {
            foreignKeyName: "leads_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["user_id"]
          },
          {
            foreignKeyName: "leads_score_id_fkey"
            columns: ["score_id"]
            isOneToOne: false
            referencedRelation: "scores"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      v_primary_contact: {
        Row: {
          business_id: string | null
          contact_id: string | null
          email: string | null
          is_decision_maker: boolean | null
          line: string | null
          line_why: string | null
          name: string | null
          phone_e164: string | null
          phone_type: string | null
          role: string | null
          source: string | null
          source_url: string | null
          verified: boolean | null
        }
        Relationships: [
          {
            foreignKeyName: "contacts_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "contacts_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
        ]
      }
      v_quota_month: {
        Row: {
          calls: number | null
          provider: string | null
          task: string | null
        }
        Relationships: []
      }
      v_quota_today: {
        Row: {
          calls: number | null
          provider: string | null
          task: string | null
        }
        Relationships: []
      }
      v_sheet_leads: {
        Row: {
          angle: string | null
          business_id: string | null
          call_at: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          country: string | null
          d3_at: string | null
          d7_at: string | null
          deal_value_inr: number | null
          due_at: string | null
          email: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          judge_note: string | null
          lead_id: string | null
          lead_updated_at: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          name: string | null
          next_step: string | null
          notes: string | null
          phone_e164: string | null
          phone_source: string | null
          phone_type: string | null
          pitch_mode: string | null
          reasons: Json | null
          score_total: number | null
          segment_id: string | null
          stage: string | null
          test_group: string | null
          top_signal_at: string | null
          top_signal_quote: string | null
          top_signal_type: string | null
          top_signal_url: string | null
          wa_at: string | null
          website: string | null
        }
        Relationships: [
          {
            foreignKeyName: "businesses_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      v_source_health: {
        Row: {
          blocked_until: string | null
          enabled: boolean | null
          health: string | null
          last_error: string | null
          last_error_at: string | null
          last_ok_at: string | null
          recent_blocks: string[] | null
          requests_day: string | null
          requests_today: number | null
          source: string | null
        }
        Insert: {
          blocked_until?: string | null
          enabled?: boolean | null
          health?: never
          last_error?: string | null
          last_error_at?: string | null
          last_ok_at?: string | null
          recent_blocks?: string[] | null
          requests_day?: string | null
          requests_today?: number | null
          source?: string | null
        }
        Update: {
          blocked_until?: string | null
          enabled?: boolean | null
          health?: never
          last_error?: string | null
          last_error_at?: string | null
          last_ok_at?: string | null
          recent_blocks?: string[] | null
          requests_day?: string | null
          requests_today?: number | null
          source?: string | null
        }
        Relationships: []
      }
      v_spend_today: {
        Row: {
          inr: number | null
          usd: number | null
        }
        Relationships: []
      }
      v_today: {
        Row: {
          angle: string | null
          business_id: string | null
          channel: string | null
          city: string | null
          company: string | null
          contact_name: string | null
          contact_role: string | null
          country: string | null
          created_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          grade: string | null
          lead_id: string | null
          message: string | null
          message_alt: string | null
          phone_e164: string | null
          phone_source: string | null
          phone_type: string | null
          pitch_mode: string | null
          segment_id: string | null
          test_group: string | null
          top_signal_at: string | null
          top_signal_quote: string | null
          top_signal_type: string | null
          top_signal_url: string | null
          total: number | null
        }
        Relationships: [
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
          {
            foreignKeyName: "leads_segment_id_fkey"
            columns: ["segment_id"]
            isOneToOne: false
            referencedRelation: "segments"
            referencedColumns: ["id"]
          },
        ]
      }
      v_top_signal: {
        Row: {
          business_id: string | null
          category: string | null
          expires_at: string | null
          observed_at: string | null
          points: number | null
          quote: string | null
          signal_id: string | null
          type: string | null
          url: string | null
        }
        Relationships: [
          {
            foreignKeyName: "signals_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "signals_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
        ]
      }
      v_verified_facts: {
        Row: {
          business_id: string | null
          created_at: string | null
          field: string | null
          id: string | null
          model: string | null
          page_id: string | null
          quote: string | null
          url: string | null
          value: Json | null
          verified: boolean | null
          verified_at: string | null
          verify_score: number | null
        }
        Relationships: [
          {
            foreignKeyName: "facts_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "businesses"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "facts_business_id_fkey"
            columns: ["business_id"]
            isOneToOne: false
            referencedRelation: "v_sheet_leads"
            referencedColumns: ["business_id"]
          },
          {
            foreignKeyName: "facts_page_id_fkey"
            columns: ["page_id"]
            isOneToOne: false
            referencedRelation: "pages"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Functions: {
      auth_role: { Args: never; Returns: string }
      _call_item: { Args: { lead_id: string }; Returns: Json }
      calls_page: { Args: never; Returns: Json }
      custom_access_token_hook: { Args: { event: Json }; Returns: Json }
      db_size_mb: { Args: never; Returns: number }
      deals_board: {
        Args: { closed_per_stage?: number; filters?: Json; max_per_stage?: number }
        Returns: Json
      }
      engine_counts: { Args: never; Returns: Json }
      home_summary: { Args: { list_limit?: number }; Returns: Json }
      _inbox_item: {
        Args: { at: string; message_id: string; tab: string; thread_id: string }
        Returns: Json
      }
      inbox_page: {
        Args: {
          cursor_at?: string
          cursor_id?: string
          page_size?: number
          tab?: string
        }
        Returns: Json
      }
      insights_summary: {
        Args: { filters?: Json; from_ts: string; to_ts: string }
        Returns: Json
      }
      lead_conversation: { Args: { lead_id: string }; Returns: Json }
      lead_detail: {
        Args: { include_unverified?: boolean; lead_id: string }
        Returns: Json
      }
      leads_page: {
        Args: { filters?: Json; page?: number; page_size?: number }
        Returns: Json
      }
      nav_counts: { Args: never; Returns: Json }
      review_message: {
        Args: { action: string; body?: string; message_id: string; subject?: string }
        Returns: Json
      }
      revoke_user_sessions: { Args: { target_user: string }; Returns: number }
      save_call_notes: { Args: { lead_id: string; notes: string }; Returns: Json }
      search_leads: { Args: { max?: number; q: string }; Returns: Json }
      today_overnight: { Args: never; Returns: Json }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
