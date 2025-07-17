//supabaseClient.js
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = 'https://ulnoqchwdlcaneifogdz.supabase.co';
const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVsbm9xY2h3ZGxjYW5laWZvZ2R6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTI3ODkzODAsImV4cCI6MjA2ODM2NTM4MH0.cuBr-_Fe4lmHdu85hSF39Z60vb8Ogfue57TeJmPKPVQ';

export const supabase = createClient(supabaseUrl, supabaseKey);
