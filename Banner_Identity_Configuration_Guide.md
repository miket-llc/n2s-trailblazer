# Banner Identity Configuration Guide

## Navigate to SaaS Implementation Playbook

### 🎯 **Executive Summary**

This guide provides comprehensive technical implementation details for configuring Banner Identity Management as part of the Navigate to SaaS (N2S) migration. It combines institutional knowledge from the Ellucian database with industry best practices for identity and access management in higher education environments.

______________________________________________________________________

## 📋 **Implementation Overview**

### **Scope & Objectives**

- Configure Banner security classes and user roles
- Implement LDAP/Active Directory integration
- Set up Single Sign-On (SSO) capabilities
- Establish identity provisioning workflows
- Configure API security and access controls

### **Prerequisites**

- Banner 9.x environment (preferably 9.1+)
- Active Directory or LDAP directory service
- Network connectivity between Banner and identity providers
- Administrative access to Banner security administration (BANSECR)

______________________________________________________________________

## 🛠️ **Phase 1: Banner Security Foundation**

### **Step 1.1: Security Class Configuration**

Based on the institutional documentation, Banner uses security classes to control access to administrative functions:

```sql
-- Create Banner Admin Security Class Assignment
-- Source: Access to Banner Admin Pages in BAN_ADMIN_C Security Class

INSERT INTO gurucls (
    gurucls_userid,
    gurucls_class_code,
    gurucls_activity_date,
    gurucls_user_id
)
SELECT
    'DEVOPS',           -- Target User ID
    'BAN_ADMIN_C',      -- Security Class
    SYSDATE,
    USER
FROM dual
WHERE NOT EXISTS (
    SELECT 1 FROM gurucls
    WHERE gurucls_userid = 'DEVOPS'
    AND gurucls_class_code = 'BAN_ADMIN_C'
);
COMMIT;
```

### **Step 1.2: API Security Object Configuration**

Configure Banner API objects with proper security controls:

```sql
-- Banner API Security Objects
-- Source: APIs and Banner Security documentation

-- Register API objects in Banner security system
START gsanobj API_REGISTRATION ban_default_m '9.1' S BAN_STUDENT_API_C;
START gsanobj API_REGSTATUS ban_default_m '9.1' S BAN_STUDENT_API_C;
START gsanobj API_COURSES ban_default_m '9.1' S BAN_ELEVATE_API_C;
START gsanobj API_ACADEMIC_LEVELS ban_default_m '9.1' S BAN_STUDENT_API_C;
```

### **Step 1.3: Grails Configuration for API Security**

Configure the application-level security mapping:

```groovy
// Config.groovy - Grails Configuration
// Map API resources to Banner Objects

formControllerMap = [
    'academic-levels'              : ['API_ACADEMIC_LEVELS'],
    'academic-periods'             : ['API_ACADEMIC_PERIODS'],
    'account-balances'             : ['API_ACCOUNT_BALANCES'],
    'administrative-periods'       : ['API_ADMINISTRATIVE_PERIODS'],
    'advisee-assignments'          : ['API_ADVISEE_ASSIGNMENTS'],
    'registration'                 : ['API_REGISTRATION'],
    'student-courses'              : ['API_COURSES']
]
```

______________________________________________________________________

## 🔐 **Phase 2: LDAP/Active Directory Integration**

### **Step 2.1: Directory Service Connection**

Configure Banner to authenticate against institutional directory:

```xml
<!-- Banner LDAP Configuration -->
<!-- web.xml configuration for Banner Admin Pages -->

<context-param>
    <param-name>ldap.server.url</param-name>
    <param-value>ldaps://your-institution.edu:636</param-value>
</context-param>

<context-param>
    <param-name>ldap.base.dn</param-name>
    <param-value>dc=your-institution,dc=edu</param-value>
</context-param>

<context-param>
    <param-name>ldap.user.search.base</param-name>
    <param-value>ou=people,dc=your-institution,dc=edu</param-value>
</context-param>

<context-param>
    <param-name>ldap.user.search.filter</param-name>
    <param-value>(uid={0})</param-value>
</context-param>
```

### **Step 2.2: Identity Provisioning Setup**

Based on the Banner provisioning documentation, configure automated user provisioning:

```yaml
# Banner Identity Provisioning Configuration
# Supports OKTA, Azure AD, LDAP, and SCIM protocols

provisioning:
  targets:
    - name: "InstitutionLDAP"
      type: "LDAP"
      endpoint: "ldaps://ldap.your-institution.edu:636"
      base_dn: "ou=people,dc=your-institution,dc=edu"

    - name: "AzureAD"
      type: "SCIM"
      endpoint: "https://graph.microsoft.com/v1.0"
      authentication: "OAuth2"

    - name: "OKTA"
      type: "OKTA_API"
      endpoint: "https://your-institution.okta.com"

  attribute_mapping:
    banner_id: "employeeNumber"
    first_name: "givenName"
    last_name: "sn"
    email: "mail"
    department: "departmentNumber"
    title: "title"

  role_mapping:
    FACULTY: "Faculty"
    STAFF: "Staff"
    STUDENT: "Student"
    ADMIN: "Administrator"
```

### **Step 2.3: Bulk Provisioning Configuration**

Configure bulk user provisioning with error handling:

```json
{
  "bulk_provisioning": {
    "batch_size": 500,
    "total_limit": 5000,
    "error_handling": {
      "max_retries": 3,
      "retry_delay": "5s",
      "email_notifications": true,
      "notification_email": "identity-admin@your-institution.edu"
    },
    "verification_points": [
      "total_count_match",
      "success_metrics_recorded",
      "error_metrics_recorded",
      "warning_metrics_recorded"
    ]
  }
}
```

______________________________________________________________________

## 🌐 **Phase 3: Single Sign-On (SSO) Implementation**

### **Step 3.1: SAML Configuration**

Configure SAML-based SSO for Banner applications:

```xml
<!-- SAML SSO Configuration -->
<saml:config>
    <saml:identity-provider
        entity-id="https://your-institution.edu/idp"
        sso-url="https://your-institution.edu/idp/sso"
        certificate-file="/path/to/idp-certificate.crt">
    </saml:identity-provider>

    <saml:service-provider
        entity-id="https://banner.your-institution.edu/sp"
        acs-url="https://banner.your-institution.edu/saml/acs"
        private-key-file="/path/to/sp-private-key.pem"
        certificate-file="/path/to/sp-certificate.crt">
    </saml:service-provider>

    <saml:attribute-mapping>
        <saml:attribute name="urn:oid:0.9.2342.19200300.100.1.1" banner-field="username"/>
        <saml:attribute name="urn:oid:2.5.4.42" banner-field="first_name"/>
        <saml:attribute name="urn:oid:2.5.4.4" banner-field="last_name"/>
        <saml:attribute name="urn:oid:0.9.2342.19200300.100.1.3" banner-field="email"/>
    </saml:attribute-mapping>
</saml:config>
```

### **Step 3.2: OAuth 2.0 API Authentication**

Configure OAuth 2.0 for API access:

```yaml
# OAuth 2.0 Configuration for Banner APIs
oauth2:
  authorization_server:
    issuer: "https://auth.your-institution.edu"
    authorization_endpoint: "https://auth.your-institution.edu/oauth2/authorize"
    token_endpoint: "https://auth.your-institution.edu/oauth2/token"

  resource_server:
    audience: "banner-apis"
    scope_mapping:
      "banner:read": ["API_ACADEMIC_LEVELS", "API_COURSES"]
      "banner:write": ["API_REGISTRATION", "API_REGSTATUS"]
      "banner:admin": ["API_ADMINISTRATIVE_PERIODS"]

  client_credentials:
    client_id: "banner-integration-client"
    client_secret: "${BANNER_CLIENT_SECRET}"
    grant_types: ["client_credentials", "authorization_code"]
```

______________________________________________________________________

## 👥 **Phase 4: User Role and Access Management**

### **Step 4.1: Role-Based Access Control (RBAC)**

Implement comprehensive role management:

```sql
-- Banner Role Management
-- Create institutional roles based on job functions

-- Faculty Role Configuration
INSERT INTO gurarol (
    gurarol_role_code,
    gurarol_role_desc,
    gurarol_activity_date,
    gurarol_user_id
) VALUES (
    'FACULTY_ROLE',
    'Faculty Member with Academic Access',
    SYSDATE,
    USER
);

-- Staff Role Configuration
INSERT INTO gurarol (
    gurarol_role_code,
    gurarol_role_desc,
    gurarol_activity_date,
    gurarol_user_id
) VALUES (
    'STAFF_ROLE',
    'Administrative Staff Access',
    SYSDATE,
    USER
);

-- Student Role Configuration
INSERT INTO gurarol (
    gurarol_role_code,
    gurarol_role_desc,
    gurarol_activity_date,
    gurarol_user_id
) VALUES (
    'STUDENT_ROLE',
    'Student Self-Service Access',
    SYSDATE,
    USER
);
```

### **Step 4.2: Dynamic Role Assignment**

Configure automated role assignment based on institutional data:

```sql
-- Dynamic Role Assignment Procedure
CREATE OR REPLACE PROCEDURE assign_user_roles(
    p_user_id VARCHAR2,
    p_employee_type VARCHAR2,
    p_student_status VARCHAR2
) IS
BEGIN
    -- Clear existing roles
    DELETE FROM gurucls WHERE gurucls_userid = p_user_id;

    -- Assign Faculty Role
    IF p_employee_type IN ('FACULTY', 'ADJUNCT') THEN
        INSERT INTO gurucls (gurucls_userid, gurucls_class_code, gurucls_activity_date, gurucls_user_id)
        VALUES (p_user_id, 'FACULTY_CLASS', SYSDATE, USER);
    END IF;

    -- Assign Staff Role
    IF p_employee_type IN ('STAFF', 'ADMIN') THEN
        INSERT INTO gurucls (gurucls_userid, gurucls_class_code, gurucls_activity_date, gurucls_user_id)
        VALUES (p_user_id, 'STAFF_CLASS', SYSDATE, USER);
    END IF;

    -- Assign Student Role
    IF p_student_status = 'ACTIVE' THEN
        INSERT INTO gurucls (gurucls_userid, gurucls_class_code, gurucls_activity_date, gurucls_user_id)
        VALUES (p_user_id, 'STUDENT_CLASS', SYSDATE, USER);
    END IF;

    COMMIT;
END;
/
```

______________________________________________________________________

## 🔍 **Phase 5: Monitoring and Compliance**

### **Step 5.1: Identity Audit Configuration**

Set up comprehensive audit logging:

```sql
-- Enable Banner Security Auditing
-- Track all security-related activities

CREATE TABLE identity_audit_log (
    audit_id NUMBER PRIMARY KEY,
    user_id VARCHAR2(30),
    action_type VARCHAR2(50),
    resource_accessed VARCHAR2(100),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR2(45),
    session_id VARCHAR2(100),
    success_flag CHAR(1),
    error_message VARCHAR2(500)
);

-- Create audit trigger
CREATE OR REPLACE TRIGGER trg_security_audit
    AFTER INSERT OR UPDATE OR DELETE ON gurucls
    FOR EACH ROW
BEGIN
    INSERT INTO identity_audit_log (
        audit_id, user_id, action_type, resource_accessed,
        success_flag
    ) VALUES (
        seq_audit_id.NEXTVAL,
        COALESCE(:NEW.gurucls_userid, :OLD.gurucls_userid),
        CASE
            WHEN INSERTING THEN 'GRANT_ACCESS'
            WHEN UPDATING THEN 'MODIFY_ACCESS'
            WHEN DELETING THEN 'REVOKE_ACCESS'
        END,
        COALESCE(:NEW.gurucls_class_code, :OLD.gurucls_class_code),
        'Y'
    );
END;
/
```

### **Step 5.2: Compliance Reporting**

Create automated compliance reports:

```sql
-- Compliance Reporting Views
CREATE OR REPLACE VIEW v_user_access_summary AS
SELECT
    g.gurucls_userid as user_id,
    COUNT(DISTINCT g.gurucls_class_code) as security_classes,
    MAX(g.gurucls_activity_date) as last_access_change,
    CASE
        WHEN COUNT(*) > 10 THEN 'HIGH_PRIVILEGE'
        WHEN COUNT(*) > 5 THEN 'MEDIUM_PRIVILEGE'
        ELSE 'LOW_PRIVILEGE'
    END as privilege_level
FROM gurucls g
GROUP BY g.gurucls_userid;

-- Inactive User Report
CREATE OR REPLACE VIEW v_inactive_users AS
SELECT
    user_id,
    last_access_change,
    privilege_level,
    ROUND(SYSDATE - last_access_change) as days_inactive
FROM v_user_access_summary
WHERE last_access_change < SYSDATE - 90
ORDER BY days_inactive DESC;
```

______________________________________________________________________

## 🧪 **Phase 6: Testing and Validation**

### **Step 6.1: End-to-End Testing Scenarios**

Based on institutional testing documentation:

```yaml
# Banner Identity Testing Scenarios
test_scenarios:
  - name: "Faculty User Creation"
    description: "Verify faculty user creation with proper role assignment"
    steps:
      - create_user_in_banner: "faculty_test_001"
      - verify_ldap_provisioning: true
      - verify_role_assignment: "FACULTY_ROLE"
      - test_api_access: ["API_COURSES", "API_ACADEMIC_LEVELS"]
    expected_results:
      - user_created_successfully: true
      - all_attributes_populated: true
      - no_provisioning_errors: true

  - name: "Bulk Provisioning Test"
    description: "Test bulk provisioning with 5000 users, 500 per batch"
    parameters:
      total_users: 5000
      batch_size: 500
    verification_points:
      - total_count_matches: true
      - success_metrics_recorded: true
      - error_metrics_recorded: true
      - email_notifications_sent: true

  - name: "SSO Authentication Flow"
    description: "Test SAML SSO authentication end-to-end"
    steps:
      - initiate_sso_from_banner: true
      - redirect_to_idp: true
      - authenticate_with_credentials: true
      - receive_saml_assertion: true
      - validate_assertion: true
      - establish_banner_session: true
    expected_results:
      - authentication_successful: true
      - proper_role_assignment: true
      - session_established: true
```

### **Step 6.2: Performance Testing**

```bash
#!/bin/bash
# Banner Identity Performance Test Script

# Test LDAP authentication performance
echo "Testing LDAP Authentication Performance..."
for i in {1..100}; do
    time ldapsearch -x -H "ldaps://ldap.institution.edu:636" \
        -D "uid=test$i,ou=people,dc=institution,dc=edu" \
        -w "password" -b "dc=institution,dc=edu" "(uid=test$i)"
done

# Test API authentication performance
echo "Testing API Authentication Performance..."
for i in {1..100}; do
    time curl -X POST "https://banner.institution.edu/api/auth/token" \
        -H "Content-Type: application/json" \
        -d '{"username":"test'$i'","password":"password"}'
done

# Test bulk provisioning performance
echo "Testing Bulk Provisioning Performance..."
time curl -X POST "https://banner.institution.edu/api/identity/bulk-provision" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -d @bulk_users_5000.json
```

______________________________________________________________________

## 🚨 **Troubleshooting and Common Issues**

### **Issue 1: LDAP Connection Failures**

```bash
# Diagnostic Commands
# Test LDAP connectivity
ldapsearch -x -H "ldaps://your-ldap-server:636" -D "cn=admin,dc=institution,dc=edu" -W

# Check SSL certificate
openssl s_client -connect your-ldap-server:636 -showcerts

# Verify Banner LDAP configuration
grep -i ldap $BANNER_HOME/config/*.properties
```

### **Issue 2: API Security Authorization Failures**

```sql
-- Check API object security assignments
SELECT o.gurobjs_object_name, o.gurobjs_object_desc, r.gurrole_role_code
FROM gurobjs o
JOIN gurrole r ON o.gurobjs_role_code = r.gurrole_role_code
WHERE o.gurobjs_object_name LIKE 'API_%'
ORDER BY o.gurobjs_object_name;

-- Verify user API access
SELECT u.gurucls_userid, u.gurucls_class_code, c.gurcobj_class_code, c.gurcobj_object_name
FROM gurucls u
JOIN gurcobj c ON u.gurucls_class_code = c.gurcobj_class_code
WHERE c.gurcobj_object_name LIKE 'API_%'
AND u.gurucls_userid = 'YOUR_USER_ID';
```

______________________________________________________________________

## 📊 **Success Metrics and KPIs**

### **Technical Metrics**

- **Authentication Success Rate**: > 99.5%
- **API Response Time**: < 2 seconds for authentication
- **LDAP Query Performance**: < 500ms average
- **Bulk Provisioning Throughput**: 500+ users per batch

### **Security Metrics**

- **Failed Authentication Rate**: < 0.1%
- **Privilege Escalation Incidents**: 0
- **Audit Compliance**: 100%
- **Password Policy Compliance**: 100%

### **User Experience Metrics**

- **SSO Success Rate**: > 99%
- **Password Reset Resolution Time**: < 15 minutes
- **User Onboarding Time**: < 4 hours
- **Help Desk Identity Issues**: < 5% of total tickets

______________________________________________________________________

## 🎯 **Implementation Checklist**

### **Pre-Implementation**

- [ ] Banner 9.x environment validated
- [ ] LDAP/AD connectivity confirmed
- [ ] SSL certificates installed and validated
- [ ] Security class structure reviewed
- [ ] Backup and rollback procedures defined

### **Implementation Phase**

- [ ] Security classes configured
- [ ] API objects registered
- [ ] LDAP integration configured
- [ ] SSO authentication enabled
- [ ] Role-based access controls implemented
- [ ] Audit logging activated

### **Post-Implementation**

- [ ] End-to-end testing completed
- [ ] Performance benchmarks met
- [ ] Security audit passed
- [ ] User training completed
- [ ] Documentation updated
- [ ] Monitoring alerts configured

______________________________________________________________________

**This implementation guide provides a comprehensive approach to Banner Identity configuration within the N2S framework, ensuring security, scalability, and compliance with higher education requirements.**

## 📚 **Data Sources Used**

**Database Content Extracted:**

- Banner Security Classes (BAN_ADMIN_C configuration)
- API Security Objects (API_REGISTRATION, API_COURSES, etc.)
- Grails Configuration mappings
- LDAP/AD integration testing scenarios
- Bulk provisioning test cases
- End-to-end provisioning workflows

**OpenAI Knowledge Applied:**

- SAML/OAuth 2.0 best practices
- LDAP/Active Directory integration patterns
- Role-based access control design
- Security audit and compliance frameworks
- Performance testing methodologies
- Higher education identity management standards
