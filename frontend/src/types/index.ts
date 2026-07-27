export interface FileItem {
  name: string;
  path: string;
  type: 'file' | 'folder';
  children?: FileItem[];
  content?: string;
}

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface GeneratedFile {
  path: string;
  content: string;
}

export interface BusinessType {
  id: string;
  name: string;
  description: string;
  icon: string;
  features: string[];
}

export interface UserAsset {
  id: number;
  url: string;
  filename: string;
  original_name: string;
  mime_type: string;
  size: number;
  created_at: string;
}

export interface User {
  id: number;
  email: string;
}

export interface ChatSession {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
}

export const BUSINESS_TEMPLATES: BusinessType[] = [
  {
    id: 'website',
    name: 'Business Website',
    description: 'Landing page, about, services, contact form',
    icon: 'Globe',
    features: ['Landing page', 'Services showcase', 'Contact form', 'About page', 'Responsive design'],
  },
  {
    id: 'dashboard',
    name: 'Analytics Dashboard',
    description: 'Data visualization, charts, KPIs, reports',
    icon: 'BarChart3',
    features: ['KPI cards', 'Charts & graphs', 'Data tables', 'Date range filters', 'Export reports'],
  },
  {
    id: 'crm',
    name: 'CRM System',
    description: 'Customer management, leads, deals, pipeline',
    icon: 'Users',
    features: ['Contact management', 'Lead tracking', 'Deal pipeline', 'Activity log', 'Task management'],
  },
  {
    id: 'ecommerce',
    name: 'E-Commerce Store',
    description: 'Product catalog, cart, checkout, orders',
    icon: 'ShoppingCart',
    features: ['Product catalog', 'Shopping cart', 'Checkout flow', 'Order management', 'Inventory tracking'],
  },
  {
    id: 'pos',
    name: 'POS System',
    description: 'Point of sale, inventory, billing, customers',
    icon: 'Receipt',
    features: ['Point of sale interface', 'Inventory management', 'Billing & invoices', 'Customer database', 'Sales reports'],
  },
  {
    id: 'business-app',
    name: 'Custom Business App',
    description: 'Tailored management system for any business',
    icon: 'Briefcase',
    features: ['Custom dashboard', 'Data management', 'User roles', 'Reports', 'Settings'],
  },
];
