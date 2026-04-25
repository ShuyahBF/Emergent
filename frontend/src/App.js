import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import "@/App.css";

import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import MarketingLayout from "@/components/MarketingLayout";
import PortalLayout from "@/components/PortalLayout";

// Public
import Home from "@/pages/public/Home";
import Missions from "@/pages/public/Missions";
import Specialisations from "@/pages/public/Specialisations";
import Catalogue from "@/pages/public/Catalogue";
import Contact from "@/pages/public/Contact";
import RDV from "@/pages/public/RDV";
import Testimonials from "@/pages/public/Testimonials";
import Feedback from "@/pages/public/Feedback";

// Auth
import Login from "@/pages/auth/Login";

// Portal
import ClientDashboard from "@/pages/portal/Dashboard";
import ClientAppointments from "@/pages/portal/Appointments";
import ClientDocuments from "@/pages/portal/Documents";
import ClientInterventions from "@/pages/portal/Interventions";
import ClientUsersTracking from "@/pages/portal/UsersTracking";

// Admin
import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminClients from "@/pages/admin/AdminClients";
import AdminAppointments from "@/pages/admin/AdminAppointments";
import AdminInterventions from "@/pages/admin/AdminInterventions";
import AdminDocuments from "@/pages/admin/AdminDocuments";
import AdminContents from "@/pages/admin/AdminContents";
import AdminSettings from "@/pages/admin/AdminSettings";
import AdminContacts from "@/pages/admin/AdminContacts";
import AdminTrackedUsers from "@/pages/admin/AdminTrackedUsers";
import AdminTestimonials from "@/pages/admin/AdminTestimonials";

import ApiDocs from "@/pages/ApiDocs";

const PublicRoute = ({ children }) => <MarketingLayout>{children}</MarketingLayout>;

const Protected = ({ admin = false, children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (admin && user.role !== "admin") return <Navigate to="/portal" replace />;
  return children;
};

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster richColors position="top-right" />
        <Routes>
          {/* Public marketing */}
          <Route path="/" element={<PublicRoute><Home /></PublicRoute>} />
          <Route path="/missions" element={<PublicRoute><Missions /></PublicRoute>} />
          <Route path="/specialisations" element={<PublicRoute><Specialisations /></PublicRoute>} />
          <Route path="/catalogue" element={<PublicRoute><Catalogue /></PublicRoute>} />
          <Route path="/contact" element={<PublicRoute><Contact /></PublicRoute>} />
          <Route path="/rdv" element={<PublicRoute><RDV /></PublicRoute>} />
          <Route path="/temoignages" element={<PublicRoute><Testimonials /></PublicRoute>} />
          <Route path="/feedback/:token" element={<Feedback />} />
          <Route path="/documentation" element={<ApiDocs />} />

          {/* Auth */}
          <Route path="/login" element={<Login />} />

          {/* Client portal */}
          <Route path="/portal" element={<Protected><PortalLayout admin={false} /></Protected>}>
            <Route index element={<ClientDashboard />} />
            <Route path="appointments" element={<ClientAppointments />} />
            <Route path="documents" element={<ClientDocuments />} />
            <Route path="interventions" element={<ClientInterventions />} />
            <Route path="users" element={<ClientUsersTracking />} />
          </Route>

          {/* Admin */}
          <Route path="/admin" element={<Protected admin><PortalLayout admin /></Protected>}>
            <Route index element={<AdminDashboard />} />
            <Route path="clients" element={<AdminClients />} />
            <Route path="appointments" element={<AdminAppointments />} />
            <Route path="interventions" element={<AdminInterventions />} />
            <Route path="documents" element={<AdminDocuments />} />
            <Route path="contents" element={<AdminContents />} />
            <Route path="contacts" element={<AdminContacts />} />
            <Route path="tracked-users" element={<AdminTrackedUsers />} />
            <Route path="testimonials" element={<AdminTestimonials />} />
            <Route path="settings" element={<AdminSettings />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
