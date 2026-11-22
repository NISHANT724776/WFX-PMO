export type FieldDef = {
  key: string;
  label: string;
  type: "text" | "email" | "checkbox" | "select" | "ref" | "number" | "color";
  required?: boolean;
  options?: string[]; // select
  refPath?: string; // ref: list endpoint
  refLabel?: string;
  onlyOnCreate?: boolean;
};

export type MasterDef = { title: string; path: string; fields: FieldDef[]; columns: string[] };

export const MASTER: Record<string, MasterDef> = {
  customers: {
    title: "Customers",
    path: "/customers",
    columns: ["code", "name", "country", "is_active"],
    fields: [
      { key: "code", label: "Code", type: "text", required: true },
      { key: "name", label: "Name", type: "text", required: true },
      { key: "country", label: "Country", type: "text" },
      { key: "is_active", label: "Active", type: "checkbox" },
    ],
  },
  products: {
    title: "Products",
    path: "/products",
    columns: ["code", "name", "description", "is_active"],
    fields: [
      { key: "code", label: "Code", type: "text", required: true },
      { key: "name", label: "Name", type: "text", required: true },
      { key: "description", label: "Description", type: "text" },
      { key: "is_active", label: "Active", type: "checkbox" },
    ],
  },
  locations: {
    title: "Locations",
    path: "/locations",
    columns: ["code", "name", "country", "timezone", "is_active"],
    fields: [
      { key: "code", label: "Code", type: "text", required: true },
      { key: "name", label: "Name", type: "text", required: true },
      { key: "country", label: "Country", type: "text" },
      { key: "timezone", label: "Timezone", type: "text" },
      { key: "is_active", label: "Active", type: "checkbox" },
    ],
  },
  departments: {
    title: "Departments",
    path: "/departments",
    columns: ["code", "name", "is_active"],
    fields: [
      { key: "code", label: "Code", type: "text", required: true },
      { key: "name", label: "Name", type: "text", required: true },
      { key: "is_active", label: "Active", type: "checkbox" },
    ],
  },
  resources: {
    title: "Resources",
    path: "/resources",
    columns: ["full_name", "email", "department_id", "is_active"],
    fields: [
      { key: "full_name", label: "Full name", type: "text", required: true },
      { key: "email", label: "Email", type: "email" },
      { key: "department_id", label: "Department", type: "ref", refPath: "/departments", refLabel: "name" },
      { key: "is_active", label: "Active", type: "checkbox" },
    ],
  },
  "status-configs": {
    title: "Status Configuration",
    path: "/status-configs",
    columns: ["entity_type", "code", "label", "category", "color", "sort_order"],
    fields: [
      { key: "entity_type", label: "Entity", type: "text", required: true },
      { key: "code", label: "Code", type: "text", required: true },
      { key: "label", label: "Label", type: "text", required: true },
      {
        key: "category",
        label: "Category",
        type: "select",
        required: true,
        options: ["not_started", "in_progress", "done", "blocked", "cancelled"],
      },
      { key: "color", label: "Colour (bars and badges)", type: "color" },
      { key: "sort_order", label: "Sort order", type: "number" },
    ],
  },
};
