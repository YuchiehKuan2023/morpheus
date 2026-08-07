export interface AuthUser {
  id: number;
  username: string;
  display_name: string | null;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  analyst_role: string;
  level: number;
  avatar_color: string | null;
  avatar_initials: string | null;
  avatar_url: string | null;
}

export interface LoginResponse {
  user: AuthUser;
  token: string;
}

export interface MeResponse {
  user: AuthUser;
}
