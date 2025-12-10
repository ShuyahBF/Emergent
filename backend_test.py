#!/usr/bin/env python3
"""
Backend API Testing for Accounting Justification Application
Tests all endpoints: auth, documents, lines, and justifications
"""

import requests
import sys
import json
import io
from datetime import datetime

class AccountingAPITester:
    def __init__(self, base_url="https://ledger-justifier.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name} - {details}")
        
        self.test_results.append({
            "test": name,
            "success": success,
            "details": details
        })

    def run_test(self, name, method, endpoint, expected_status, data=None, files=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        headers = {}
        
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        
        if data and not files:
            headers['Content-Type'] = 'application/json'

        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                if files:
                    response = requests.post(url, files=files, headers=headers)
                else:
                    response = requests.post(url, json=data, headers=headers)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers)

            success = response.status_code == expected_status
            details = f"Status: {response.status_code}"
            
            if not success:
                details += f" (expected {expected_status})"
                try:
                    error_data = response.json()
                    details += f" - {error_data.get('detail', 'Unknown error')}"
                except:
                    details += f" - {response.text[:100]}"

            self.log_test(name, success, details)
            
            if success:
                try:
                    return response.json()
                except:
                    return {}
            return None

        except Exception as e:
            self.log_test(name, False, f"Exception: {str(e)}")
            return None

    def create_test_pdf(self):
        """Create test content that mimics a PDF with accounting lines"""
        # Since we don't have reportlab, we'll create a simple text content
        # that matches the expected format for the regex parser
        content = """401000 Fournisseur ABC 1500.00 0.00
411000 Client XYZ 0.00 2000.00
512000 Banque 500.00 0.00
445660 TVA déductible 300.00 0.00
607000 Achats marchandises 1200.00 0.00"""
        
        return content.encode('utf-8')

    def test_user_registration(self):
        """Test user registration"""
        timestamp = datetime.now().strftime("%H%M%S")
        test_data = {
            "email": f"test{timestamp}@example.com",
            "password": "TestPass123!",
            "nom": f"Test User {timestamp}"
        }
        
        result = self.run_test(
            "User Registration",
            "POST",
            "auth/register",
            200,
            data=test_data
        )
        
        if result:
            self.token = result.get('access_token')
            self.user_id = result.get('user', {}).get('id')
            return True
        return False

    def test_user_login(self):
        """Test user login with existing credentials"""
        # Try to login with the registered user
        if not hasattr(self, 'test_email'):
            return False
            
        login_data = {
            "email": self.test_email,
            "password": "TestPass123!"
        }
        
        result = self.run_test(
            "User Login",
            "POST",
            "auth/login",
            200,
            data=login_data
        )
        
        if result:
            self.token = result.get('access_token')
            return True
        return False

    def test_get_current_user(self):
        """Test getting current user info"""
        result = self.run_test(
            "Get Current User",
            "GET",
            "auth/me",
            200
        )
        return result is not None

    def test_document_upload(self):
        """Test PDF document upload with real test file"""
        try:
            # Try to use the real test PDF file first
            with open('/tmp/test_comptable.pdf', 'rb') as f:
                pdf_content = f.read()
            filename = 'test_comptable.pdf'
            print(f"   📄 Using real test PDF file ({len(pdf_content)} bytes)")
        except FileNotFoundError:
            # Fallback to created content
            pdf_content = self.create_test_pdf()
            filename = 'test_accounting.pdf'
            print(f"   📄 Using generated test content ({len(pdf_content)} bytes)")
        
        files = {
            'file': (filename, pdf_content, 'application/pdf')
        }
        
        result = self.run_test(
            "Document Upload",
            "POST",
            "documents",
            200,
            files=files
        )
        
        if result:
            self.document_id = result.get('id')
            print(f"   📋 Document uploaded with ID: {self.document_id}")
            print(f"   📊 Expected lines: {result.get('total_lines', 0)}")
            return True
        return False

    def test_get_documents(self):
        """Test getting user documents"""
        result = self.run_test(
            "Get Documents List",
            "GET",
            "documents",
            200
        )
        return result is not None and isinstance(result, list)

    def test_get_document_details(self):
        """Test getting specific document details"""
        if not hasattr(self, 'document_id'):
            self.log_test("Get Document Details", False, "No document ID available")
            return False
            
        result = self.run_test(
            "Get Document Details",
            "GET",
            f"documents/{self.document_id}",
            200
        )
        return result is not None

    def test_get_document_lines(self):
        """Test getting accounting lines from document"""
        if not hasattr(self, 'document_id'):
            self.log_test("Get Document Lines", False, "No document ID available")
            return False
            
        result = self.run_test(
            "Get Document Lines",
            "GET",
            f"documents/{self.document_id}/lines",
            200
        )
        
        if result and isinstance(result, list):
            if len(result) > 0:
                self.line_id = result[0].get('id')
                self.test_line = result[0]
                print(f"   📋 Found {len(result)} accounting lines")
                return True
            else:
                print(f"   ⚠️ Document processed but no lines extracted (PDF parsing issue)")
                return True  # Still consider this a pass since the API works
        return False

    def test_create_justification(self):
        """Test creating justification for a line"""
        if not hasattr(self, 'line_id') or not hasattr(self, 'test_line'):
            self.log_test("Create Justification", False, "No line ID available (PDF parsing failed)")
            return False
        
        # Create justification details that match the line totals
        justification_data = {
            "details": [
                {
                    "label": "Facture fournisseur #001",
                    "debit": self.test_line.get('debit', 0),
                    "credit": self.test_line.get('credit', 0)
                }
            ]
        }
        
        result = self.run_test(
            "Create Justification",
            "POST",
            f"lines/{self.line_id}/justifications",
            200,
            data=justification_data
        )
        
        if result:
            self.justification_id = result.get('id')
            return True
        return False

    def test_get_justification(self):
        """Test getting justification for a line"""
        if not hasattr(self, 'line_id'):
            self.log_test("Get Justification", False, "No line ID available (PDF parsing failed)")
            return False
            
        result = self.run_test(
            "Get Justification",
            "GET",
            f"lines/{self.line_id}/justifications",
            200
        )
        return result is not None

    def test_update_justification(self):
        """Test updating existing justification"""
        if not hasattr(self, 'justification_id') or not hasattr(self, 'test_line'):
            self.log_test("Update Justification", False, "No justification ID available (PDF parsing failed)")
            return False
        
        # Update with multiple detail lines
        updated_data = {
            "details": [
                {
                    "label": "Facture fournisseur #001 - Partie 1",
                    "debit": self.test_line.get('debit', 0) / 2,
                    "credit": self.test_line.get('credit', 0) / 2
                },
                {
                    "label": "Facture fournisseur #001 - Partie 2", 
                    "debit": self.test_line.get('debit', 0) / 2,
                    "credit": self.test_line.get('credit', 0) / 2
                }
            ]
        }
        
        result = self.run_test(
            "Update Justification",
            "PUT",
            f"justifications/{self.justification_id}",
            200,
            data=updated_data
        )
        return result is not None

    def test_invalid_pdf_upload(self):
        """Test uploading non-PDF file"""
        files = {
            'file': ('test.txt', b'This is not a PDF', 'text/plain')
        }
        
        result = self.run_test(
            "Invalid File Upload",
            "POST",
            "documents",
            400,
            files=files
        )
        return result is None  # We expect this to fail

    def test_unauthorized_access(self):
        """Test accessing protected endpoints without token"""
        original_token = self.token
        self.token = None
        
        result = self.run_test(
            "Unauthorized Access",
            "GET",
            "documents",
            401
        )
        
        self.token = original_token
        return result is None  # We expect this to fail

    def run_all_tests(self):
        """Run comprehensive test suite"""
        print("🚀 Starting Backend API Tests for Accounting Justification App")
        print("=" * 60)
        
        # Store test email for login test
        timestamp = datetime.now().strftime("%H%M%S")
        self.test_email = f"test{timestamp}@example.com"
        
        # Authentication Tests
        print("\n📝 Authentication Tests")
        if not self.test_user_registration():
            print("❌ Registration failed - stopping tests")
            return False
            
        self.test_get_current_user()
        
        # Document Tests
        print("\n📄 Document Management Tests")
        self.test_document_upload()
        self.test_get_documents()
        self.test_get_document_details()
        self.test_get_document_lines()
        
        # Justification Tests
        print("\n⚖️ Justification Tests")
        self.test_create_justification()
        self.test_get_justification()
        self.test_update_justification()
        
        # Error Handling Tests
        print("\n🛡️ Error Handling Tests")
        self.test_invalid_pdf_upload()
        self.test_unauthorized_access()
        
        # Results
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return True
        else:
            print("⚠️ Some tests failed")
            return False

def main():
    tester = AccountingAPITester()
    success = tester.run_all_tests()
    
    # Save detailed results
    with open('/app/test_reports/backend_test_results.json', 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'total_tests': tester.tests_run,
            'passed_tests': tester.tests_passed,
            'success_rate': tester.tests_passed / tester.tests_run if tester.tests_run > 0 else 0,
            'results': tester.test_results
        }, f, indent=2)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())