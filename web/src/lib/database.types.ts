// Database types for the public schema.
// Generated: run `pnpm db:types` (needs SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF) after every migration.
// Do not edit by hand.

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
      contacts: {
        Row: {
          business_id: string
          created_at: string
          do_not_contact: boolean
          email: string | null
          id: string
          is_decision_maker: boolean
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
      leads: {
        Row: {
          angle: string | null
          business_id: string
          call_at: string | null
          channel: string
          created_at: string
          d3_at: string | null
          d7_at: string | null
          deal_value_inr: number | null
          due_at: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string
          id: string
          last_activity_at: string
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
          deal_value_inr?: number | null
          due_at?: string | null
          email_body?: string | null
          email_subject?: string | null
          followup_d3?: string | null
          followup_d7?: string | null
          grade: string
          id?: string
          last_activity_at?: string
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
          deal_value_inr?: number | null
          due_at?: string | null
          email_body?: string | null
          email_subject?: string | null
          followup_d3?: string | null
          followup_d7?: string | null
          grade?: string
          id?: string
          last_activity_at?: string
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
      db_size_mb: { Args: never; Returns: number }
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
