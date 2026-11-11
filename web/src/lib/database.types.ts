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
        ]
      }
      costs: {
        Row: {
          at: string
          calls: number
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
          segment_id: string | null
          status: string
          text: string
          url: string | null
        }
        Insert: {
          created_at?: string
          created_by?: string | null
          id?: string
          segment_id?: string | null
          status?: string
          text: string
          url?: string | null
        }
        Update: {
          created_at?: string
          created_by?: string | null
          id?: string
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
            isOneToOne: true
            referencedRelation: "businesses"
            referencedColumns: ["id"]
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
          user_id: string
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
        ]
      }
      source_health: {
        Row: {
          blocked_until: string | null
          enabled: boolean
          last_error: string | null
          last_error_at: string | null
          last_ok_at: string | null
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
    }
    Views: {
      v_costs_daily: {
        Row: {
          calls: number | null
          day: string | null
          input_tokens: number | null
          inr: number | null
          model: string | null
          output_tokens: number | null
          provider: string | null
          task: string | null
          usd: number | null
        }
        Relationships: []
      }
      v_followups_due: {
        Row: {
          angle: string | null
          business_id: string | null
          business_name: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          contact_source: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          domain: string | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          judge_note: string | null
          last_activity_at: string | null
          lead_id: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          score_total: number | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          updated_at: string | null
          wa_at: string | null
          website: string | null
        }
        Relationships: []
      }
      v_funnel: {
        Row: {
          angle: string | null
          contacted: number | null
          country: string | null
          domain: string | null
          grade: string | null
          leads: number | null
          meetings: number | null
          pitch_mode: string | null
          proposals: number | null
          replied: number | null
          segment_id: string | null
          test_group: string | null
          won: number | null
          wrong_contact: number | null
        }
        Relationships: []
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
      v_leads_admin: {
        Row: {
          angle: string | null
          business_id: string | null
          business_name: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          contact_source: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          deal_value_inr: number | null
          domain: string | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          judge_note: string | null
          last_activity_at: string | null
          lead_id: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          score_total: number | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          updated_at: string | null
          wa_at: string | null
          website: string | null
        }
        Relationships: []
      }
      v_leads_caller: {
        Row: {
          angle: string | null
          business_id: string | null
          business_name: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          contact_source: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          domain: string | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          judge_note: string | null
          last_activity_at: string | null
          lead_id: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          score_total: number | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          updated_at: string | null
          wa_at: string | null
          website: string | null
        }
        Relationships: []
      }
      v_pipeline: {
        Row: {
          angle: string | null
          business_id: string | null
          business_name: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          contact_source: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          deal_value_inr: number | null
          domain: string | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          judge_note: string | null
          last_activity_at: string | null
          lead_id: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          score_total: number | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          updated_at: string | null
          wa_at: string | null
          website: string | null
        }
        Relationships: []
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
        Relationships: []
      }
      v_source_health: {
        Row: {
          blocked_until: string | null
          enabled: boolean | null
          health: string | null
          last_error: string | null
          last_error_at: string | null
          last_ok_at: string | null
          requests_day: string | null
          requests_today: number | null
          source: string | null
        }
        Relationships: []
      }
      v_today: {
        Row: {
          angle: string | null
          business_id: string | null
          business_name: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          contact_source: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          domain: string | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          judge_note: string | null
          last_activity_at: string | null
          lead_id: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          score_total: number | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          updated_at: string | null
          wa_at: string | null
          website: string | null
        }
        Relationships: []
      }
      v_today_queue: {
        Row: {
          angle: string | null
          business_id: string | null
          business_name: string | null
          call_at: string | null
          category: string | null
          channel: string | null
          city: string | null
          contact_name: string | null
          contact_role: string | null
          contact_source: string | null
          country: string | null
          created_at: string | null
          d3_at: string | null
          d7_at: string | null
          domain: string | null
          due_at: string | null
          email: string | null
          email_body: string | null
          email_subject: string | null
          followup_d3: string | null
          followup_d7: string | null
          grade: string | null
          judge_note: string | null
          last_activity_at: string | null
          lead_id: string | null
          locality: string | null
          meeting_at: string | null
          message: string | null
          message_alt: string | null
          next_step: string | null
          notes: string | null
          owner_id: string | null
          phone_e164: string | null
          phone_type: string | null
          pitch_mode: string | null
          regen_requested_at: string | null
          score_total: number | null
          segment_id: string | null
          skipped_until: string | null
          stage: string | null
          subcategory: string | null
          test_group: string | null
          updated_at: string | null
          wa_at: string | null
          website: string | null
        }
        Relationships: []
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
        Relationships: []
      }
    }
    Functions: {
      auth_role: { Args: never; Returns: string }
      db_size_mb: { Args: never; Returns: number }
      mark_wrong_contact: { Args: { p_lead_id: string; p_reason?: string }; Returns: undefined }
      set_user_role: { Args: { p_user_id: string; p_role: string }; Returns: undefined }
      spend_today_inr: { Args: never; Returns: number }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type PublicSchema = Database['public']

export type Tables<T extends keyof PublicSchema['Tables']> = PublicSchema['Tables'][T]['Row']
export type TablesInsert<T extends keyof PublicSchema['Tables']> = PublicSchema['Tables'][T]['Insert']
export type TablesUpdate<T extends keyof PublicSchema['Tables']> = PublicSchema['Tables'][T]['Update']
export type Views<T extends keyof PublicSchema['Views']> = PublicSchema['Views'][T]['Row']
