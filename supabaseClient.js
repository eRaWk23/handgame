import { createClient } from 'https://esm.sh/@supabase/supabase-js';

const supabaseUrl = 'https://atorftwulkabkmhaeeir.supabase.co';
const supabaseKey = 'sb_publishable_0CKKNOHPd3Yd6bDfkEuHlA_YgS9bJvF';

export const supabase = createClient(supabaseUrl, supabaseKey);
