# Banner Identity Technical Implementation Guide

## Post-Workshop Configuration for Technical Architects

### 🎯 **Purpose**

This guide provides **step-by-step technical implementation procedures** for configuring Banner Identity Management after workshop requirements have been gathered. It bridges the gap between consultant workshops and hands-on technical configuration.

**Target Audience**: Technical Architects, Banner Administrators, Identity Management Teams
**Prerequisites**: Completed Discovery Workshops, approved Architecture Design, stakeholder sign-off

______________________________________________________________________

## 📋 **Implementation Roadmap Overview**

Based on institutional workshop methodologies and Architecture Alignment Workshop (AAW) outputs:

1. **Banner Application Setup** (Week 1)
1. **Security Class Configuration** (Week 2)
1. **Identity Provider Integration** (Week 3-4)
1. **API Security Implementation** (Week 5)
1. **Testing and Validation** (Week 6)
1. **Go-Live Preparation** (Week 7-8)

______________________________________________________________________

## 🏗️ **Phase 1: Banner Application Setup**

### **Step 1.1: Create Banner Application in Ethos Integration**

**Reference**: Based on institutional testing procedures for Banner application creation

**Procedure**:

1. Navigate to Ethos Integration Hub applications overview page
1. Select **'Add Application'**
1. Select **'From Catalog'**
1. Select **'Ellucian Banner'**
1. Enter Application Name: `"Banner Identity - [Institution Name] - [Date]"`
1. Enter the Banner API Base URI: `https://[your-banner-host]/StudentApi/api`
1. Enter Banner API credentials:
   - Username: `grails_user` (or institutional service account)
   - Password: `[from workshop requirements]`
1. Select **'Next'**
1. Select **'Skip'** (for initial setup)
1. Select **'View Application'**

**Validation Steps**:

- Validate API Keys Tab shows exactly 1 API Key
- Select **'Owned Resources'** tab and verify resources loaded
- Verify **'Credentials'** tab is properly configured
- Test connection using **'Test Connection'** button

### **Step 1.2: Configure Application Security**

**Based on institutional security validation procedures**:

1. From Application Overview, select **'API Configuration'**
1. Configure authentication type based on workshop requirements:
   - **Option A**: Basic Authentication (development/testing)
   - **Option B**: OAuth 2.0 (production recommendation)
   - **Option C**: JWT Bearer Token (high-security environments)
1. Set up Request Routing rules for institutional network topology
1. Configure rate limiting based on expected load (from workshop capacity planning)

**Documentation Reference**:

- Ethos Integration Hub User Guide: `https://ellucian.atlassian.net/wiki/spaces/EIH/pages/[page-id]`
- Banner API Security Configuration: `https://ellucian.atlassian.net/wiki/spaces/BANNER/pages/[security-config]`

______________________________________________________________________

## 🔐 **Phase 2: Banner Security Class Configuration**

### **Step 2.1: Design Security Class Structure**

**Based on workshop role mapping outputs, implement security classes**:

**Faculty Security Class**:

```sql
-- Create Faculty Security Class (run in BANSECR as BANSECR user)
INSERT INTO gurcobj (
    gurcobj_class_code,
    gurcobj_object_name,
    gurcobj_activity_date,
    gurcobj_user_id
) VALUES (
    'FACULTY_CLASS',
    'SFAREGS',  -- Faculty registration access
    SYSDATE,
    USER
);

INSERT INTO gurcobj (
    gurcobj_class_code,
    gurcobj_object_name,
    gurcobj_activity_date,
    gurcobj_user_id
) VALUES (
    'FACULTY_CLASS',
    'SFAGMNU',  -- Faculty grade entry
    SYSDATE,
    USER
);
COMMIT;
```

**Staff Security Class**:

```sql
-- Create Staff Security Class
INSERT INTO gurcobj (
    gurcobj_class_code,
    gurcobj_object_name,
    gurcobj_activity_date,
    gurcobj_user_id
) VALUES (
    'STAFF_CLASS',
    'SPAIDEN',  -- Staff demographic access
    SYSDATE,
    USER
);

INSERT INTO gurcobj (
    gurcobj_class_code,
    gurcobj_object_name,
    gurcobj_activity_date,
    gurcobj_user_id
) VALUES (
    'STAFF_CLASS',
    'SFASTDN',  -- Staff student lookup
    SYSDATE,
    USER
);
COMMIT;
```

### **Step 2.2: Assign Users to Security Classes**

**Individual User Assignment** (based on workshop RACI matrix):

```sql
-- Assign specific users to security classes
-- Template from institutional documentation

INSERT INTO gurucls (
    gurucls_userid,
    gurucls_class_code,
    gurucls_activity_date,
    gurucls_user_id
)
SELECT
    '[USERNAME_FROM_WORKSHOP]',  -- Replace with actual username
    '[SECURITY_CLASS]',          -- Replace with class from workshop design
    SYSDATE,
    USER
FROM dual
WHERE NOT EXISTS (
    SELECT 1 FROM gurucls
    WHERE gurucls_userid = '[USERNAME_FROM_WORKSHOP]'
    AND gurucls_class_code = '[SECURITY_CLASS]'
);
COMMIT;
```

**Validation Query**:

```sql
-- Verify security class assignments
SELECT
    u.gurucls_userid,
    u.gurucls_class_code,
    c.gurcobj_object_name,
    u.gurucls_activity_date
FROM gurucls u
JOIN gurcobj c ON u.gurucls_class_code = c.gurcobj_class_code
WHERE u.gurucls_userid = '[USERNAME_TO_VERIFY]'
ORDER BY u.gurucls_class_code, c.gurcobj_object_name;
```

______________________________________________________________________

## 🔗 **Phase 3: LDAP/Active Directory Integration**

### **Step 3.1: Configure LDAP Authentication**

**Banner LDAP Configuration** (based on institutional authentication methods):

**File**: `$BANNER_HOME/tomcat/conf/web.xml`

```xml
<!-- LDAP Authentication Configuration -->
<context-param>
    <param-name>ldap.authentication.enabled</param-name>
    <param-value>true</param-value>
</context-param>

<context-param>
    <param-name>ldap.server.url</param-name>
    <param-value>ldaps://[YOUR_LDAP_SERVER]:636</param-value>
</context-param>

<context-param>
    <param-name>ldap.base.dn</param-name>
    <param-value>dc=[YOUR_INSTITUTION],dc=edu</param-value>
</context-param>

<context-param>
    <param-name>ldap.user.search.base</param-name>
    <param-value>ou=people,dc=[YOUR_INSTITUTION],dc=edu</param-value>
</context-param>

<context-param>
    <param-name>ldap.user.search.filter</param-name>
    <param-value>(uid={0})</param-value>
</context-param>

<context-param>
    <param-name>ldap.group.search.base</param-name>
    <param-value>ou=groups,dc=[YOUR_INSTITUTION],dc=edu</param-value>
</context-param>
```

### **Step 3.2: Test LDAP Connection**

**Validation Commands** (run from Banner application server):

```bash
# Test LDAP connectivity
ldapsearch -x -H "ldaps://[YOUR_LDAP_SERVER]:636" \
  -D "cn=banner-service,ou=services,dc=[YOUR_INSTITUTION],dc=edu" \
  -W -b "ou=people,dc=[YOUR_INSTITUTION],dc=edu" \
  "(uid=[TEST_USERNAME])"

# Test SSL certificate
openssl s_client -connect [YOUR_LDAP_SERVER]:636 -showcerts

# Verify Banner can read LDAP attributes
curl -X POST "https://[BANNER_HOST]/BannerAdmin/ldap/test" \
  -H "Content-Type: application/json" \
  -d '{"username":"[TEST_USER]","password":"[TEST_PASSWORD]"}'
```

### **Step 3.3: Configure Attribute Mapping**

**Banner LDAP Attribute Mapping** (customize based on workshop requirements):

```properties
# File: $BANNER_HOME/config/ldap.properties
ldap.attribute.mapping.username=uid
ldap.attribute.mapping.email=mail
ldap.attribute.mapping.first_name=givenName
ldap.attribute.mapping.last_name=sn
ldap.attribute.mapping.employee_id=employeeNumber
ldap.attribute.mapping.department=departmentNumber
ldap.attribute.mapping.title=title
ldap.attribute.mapping.phone=telephoneNumber

# Group membership mapping
ldap.group.mapping.faculty=cn=faculty,ou=groups,dc=[YOUR_INSTITUTION],dc=edu
ldap.group.mapping.staff=cn=staff,ou=groups,dc=[YOUR_INSTITUTION],dc=edu
ldap.group.mapping.student=cn=students,ou=groups,dc=[YOUR_INSTITUTION],dc=edu
```

______________________________________________________________________

## 🌐 **Phase 4: Single Sign-On (SSO) Configuration**

### **Step 4.1: SAML Identity Provider Setup**

**Banner SAML Configuration** (production-ready approach):

**File**: `$BANNER_HOME/config/saml.xml`

```xml
<!-- SAML 2.0 Configuration -->
<saml:config>
    <saml:identity-provider
        entity-id="https://[YOUR_INSTITUTION].edu/idp"
        sso-url="https://[YOUR_INSTITUTION].edu/idp/profile/SAML2/Redirect/SSO"
        slo-url="https://[YOUR_INSTITUTION].edu/idp/profile/SAML2/Redirect/SLO"
        certificate-location="/opt/banner/security/idp-certificate.pem">
    </saml:identity-provider>

    <saml:service-provider
        entity-id="https://banner.[YOUR_INSTITUTION].edu"
        acs-url="https://banner.[YOUR_INSTITUTION].edu/saml/acs"
        sls-url="https://banner.[YOUR_INSTITUTION].edu/saml/sls"
        private-key-location="/opt/banner/security/sp-private-key.pem"
        certificate-location="/opt/banner/security/sp-certificate.pem">
    </saml:service-provider>
</saml:config>
```

### **Step 4.2: Configure SAML Attribute Mapping**

**Based on workshop user attribute requirements**:

```xml
<!-- SAML Attribute Mapping -->
<saml:attribute-mapping>
    <!-- Core Identity Attributes -->
    <saml:attribute
        name="urn:oid:0.9.2342.19200300.100.1.1"
        banner-field="GUBIDEN_ID"
        required="true"/>

    <saml:attribute
        name="urn:oid:0.9.2342.19200300.100.1.3"
        banner-field="GOREMAL_EMAIL_ADDRESS"
        required="true"/>

    <!-- Institutional Attributes -->
    <saml:attribute
        name="urn:oid:2.5.4.42"
        banner-field="SPRIDEN_FIRST_NAME"
        required="true"/>

    <saml:attribute
        name="urn:oid:2.5.4.4"
        banner-field="SPRIDEN_LAST_NAME"
        required="true"/>

    <!-- Role Attributes -->
    <saml:attribute
        name="https://[YOUR_INSTITUTION].edu/attributes/role"
        banner-field="INSTITUTIONAL_ROLE"
        required="false"/>
</saml:attribute-mapping>
```

### **Step 4.3: Test SSO Authentication Flow**

**SSO Testing Procedure**:

```bash
# Test SAML metadata exchange
curl -X GET "https://banner.[YOUR_INSTITUTION].edu/saml/metadata" \
  -H "Accept: application/xml"

# Test SSO initiation
curl -X GET "https://banner.[YOUR_INSTITUTION].edu/saml/login" \
  -L -c cookies.txt

# Validate SAML assertion processing
curl -X POST "https://banner.[YOUR_INSTITUTION].edu/saml/acs" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "SAMLResponse=[BASE64_ENCODED_ASSERTION]" \
  -b cookies.txt
```

______________________________________________________________________

## 🔑 **Phase 5: API Authentication and Authorization**

### **Step 5.1: Configure OAuth 2.0 for Banner APIs**

**OAuth Configuration** (production security approach):

**File**: `$BANNER_HOME/config/oauth.properties`

```properties
# OAuth 2.0 Configuration
oauth2.enabled=true
oauth2.issuer=https://auth.[YOUR_INSTITUTION].edu
oauth2.authorization.endpoint=https://auth.[YOUR_INSTITUTION].edu/oauth2/authorize
oauth2.token.endpoint=https://auth.[YOUR_INSTITUTION].edu/oauth2/token
oauth2.userinfo.endpoint=https://auth.[YOUR_INSTITUTION].edu/oauth2/userinfo

# Client Configuration
oauth2.client.id=banner-api-client
oauth2.client.secret=[FROM_WORKSHOP_SECURITY_REQUIREMENTS]
oauth2.scope.default=banner:read
oauth2.scope.admin=banner:admin

# Token Validation
oauth2.token.validation.endpoint=https://auth.[YOUR_INSTITUTION].edu/oauth2/introspect
oauth2.token.cache.ttl=300
```

### **Step 5.2: Map API Resources to Banner Objects**

**Grails Configuration** (based on institutional API mapping procedures):

**File**: `$BANNER_HOME/grails-app/conf/Config.groovy`

```groovy
// API Resource to Banner Object Mapping
// Based on institutional security class design from workshops

formControllerMap = [
    // Student APIs (Faculty Access)
    'academic-levels'              : ['API_ACADEMIC_LEVELS'],
    'academic-periods'             : ['API_ACADEMIC_PERIODS'],
    'courses'                      : ['API_COURSES'],
    'course-sections'              : ['API_SECTIONS'],
    'students'                     : ['API_STUDENTS'],

    // Administrative APIs (Staff Access)
    'account-balances'             : ['API_ACCOUNT_BALANCES'],
    'administrative-periods'       : ['API_ADMINISTRATIVE_PERIODS'],
    'financial-aid'                : ['API_FINANCIAL_AID'],

    // Registration APIs (Student + Faculty)
    'registration'                 : ['API_REGISTRATION'],
    'registration-status'          : ['API_REGSTATUS'],
    'advisee-assignments'          : ['API_ADVISEE_ASSIGNMENTS'],

    // Reporting APIs (Administrative)
    'institutional-reporting'      : ['API_REPORTING'],
    'data-extracts'               : ['API_DATA_EXTRACTS']
]

// OAuth Scope to Security Class Mapping
oauthScopeMapping = [
    'banner:read': [
        'FACULTY_CLASS',
        'STAFF_CLASS',
        'STUDENT_CLASS'
    ],
    'banner:write': [
        'FACULTY_CLASS',
        'STAFF_CLASS'
    ],
    'banner:admin': [
        'BAN_ADMIN_C'
    ]
]
```

### **Step 5.3: Implement API Security Validation**

**Banner API Security Implementation**:

**File**: `$BANNER_HOME/src/groovy/BannerApiSecurity.groovy`

```groovy
class BannerApiSecurity {

    static validateApiAccess(String userId, String apiResource) {
        // Get user's security classes
        def userClasses = getUserSecurityClasses(userId)

        // Get required Banner objects for API resource
        def requiredObjects = getRequiredBannerObjects(apiResource)

        // Validate access
        return userClasses.any { securityClass ->
            hasAccessToObjects(securityClass, requiredObjects)
        }
    }

    static getUserSecurityClasses(String userId) {
        def sql = """
            SELECT gurucls_class_code
            FROM gurucls
            WHERE gurucls_userid = :userId
        """
        return executeQuery(sql, [userId: userId])
    }

    static getRequiredBannerObjects(String apiResource) {
        def mapping = grailsApplication.config.formControllerMap
        return mapping[apiResource] ?: []
    }
}
```

______________________________________________________________________

## 🧪 **Phase 6: Testing and Validation Procedures**

### **Step 6.1: Authentication Testing**

**Test Suite** (based on institutional regression testing procedures):

```bash
#!/bin/bash
# Banner Identity Authentication Test Suite

echo "Testing Banner Identity Configuration..."

# Test 1: LDAP Authentication
echo "1. Testing LDAP Authentication..."
curl -X POST "https://[BANNER_HOST]/BannerAdmin/api/auth/ldap" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "[TEST_FACULTY_USER]",
    "password": "[TEST_PASSWORD]"
  }'

# Test 2: SAML SSO Flow
echo "2. Testing SAML SSO..."
curl -X GET "https://[BANNER_HOST]/saml/login" \
  -L -c test_cookies.txt

# Test 3: API Authentication
echo "3. Testing API Authentication..."
TOKEN=$(curl -X POST "https://auth.[YOUR_INSTITUTION].edu/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=[CLIENT_ID]&client_secret=[CLIENT_SECRET]" \
  | jq -r '.access_token')

curl -X GET "https://[BANNER_HOST]/api/students" \
  -H "Authorization: Bearer $TOKEN"

# Test 4: Role-Based Access Control
echo "4. Testing RBAC..."
curl -X GET "https://[BANNER_HOST]/api/admin/users" \
  -H "Authorization: Bearer $TOKEN"
```

### **Step 6.2: User Acceptance Testing**

**UAT Scenarios** (from workshop user journey mapping):

```yaml
Faculty_Authentication_Test:
  Scenario: "Faculty member logs in and accesses grade entry"
  Steps:
    1. Navigate to Banner SSO login page
    2. Enter institutional credentials
    3. Verify redirect to Banner dashboard
    4. Access grade entry form (SFAGMNU)
    5. Verify proper course list appears
    6. Test grade entry functionality
  Expected_Results:
    - SSO login successful
    - Dashboard loads within 3 seconds
    - Grade entry form accessible
    - Course data populated correctly

Staff_API_Access_Test:
  Scenario: "Staff member uses API to query student information"
  Steps:
    1. Obtain API token using staff credentials
    2. Query student API endpoint
    3. Verify data returned matches security permissions
    4. Test unauthorized endpoint access (should fail)
  Expected_Results:
    - Token obtained successfully
    - Authorized data accessible
    - Unauthorized access properly blocked
    - Audit log entries created

Student_Self_Service_Test:
  Scenario: "Student accesses self-service portal"
  Steps:
    1. Student logs in via institutional SSO
    2. Access registration system
    3. View course catalog and schedule
    4. Attempt to access restricted faculty functions (should fail)
  Expected_Results:
    - SSO authentication successful
    - Self-service functions accessible
    - Restricted access properly blocked
    - User experience meets workshop requirements
```

______________________________________________________________________

## 📊 **Phase 7: Production Deployment**

### **Step 7.1: Production Environment Configuration**

**Pre-Production Checklist**:

```yaml
Security_Validation:
  - [ ] SSL certificates installed and validated
  - [ ] LDAP/SAML endpoints accessible from production network
  - [ ] API rate limiting configured per workshop requirements
  - [ ] Security class assignments match workshop RACI matrix
  - [ ] Audit logging enabled and functional

Performance_Validation:
  - [ ] Authentication response time < 2 seconds
  - [ ] API response time < 3 seconds
  - [ ] LDAP query performance < 500ms
  - [ ] SSO redirect time < 5 seconds

Compliance_Validation:
  - [ ] FERPA compliance controls implemented
  - [ ] Audit trail completeness verified
  - [ ] Data retention policies configured
  - [ ] Access control documentation complete
```

### **Step 7.2: Go-Live Support Procedures**

**Production Deployment Steps**:

```bash
#!/bin/bash
# Banner Identity Production Deployment

echo "Starting Banner Identity Production Deployment..."

# Step 1: Deploy configuration files
echo "1. Deploying configuration files..."
scp web.xml saml.xml oauth.properties [BANNER_PROD_HOST]:/opt/banner/config/

# Step 2: Restart Banner services
echo "2. Restarting Banner services..."
ssh [BANNER_PROD_HOST] "sudo systemctl restart banner-tomcat"
ssh [BANNER_PROD_HOST] "sudo systemctl restart banner-grails"

# Step 3: Validate services
echo "3. Validating services..."
curl -f "https://[BANNER_PROD_HOST]/BannerAdmin/health" || exit 1
curl -f "https://[BANNER_PROD_HOST]/api/health" || exit 1

# Step 4: Test authentication flows
echo "4. Testing authentication..."
./test_authentication_suite.sh

echo "Banner Identity deployment complete!"
```

______________________________________________________________________

## 📚 **Documentation and Reference Links**

### **Ellucian Official Documentation**

- **Banner Security Administration Guide**: `https://ellucian.atlassian.net/wiki/spaces/BANNER/pages/[security-admin]`
- **Ethos Integration Hub Setup**: `https://ellucian.atlassian.net/wiki/spaces/EIH/pages/[integration-setup]`
- **Banner API Security Reference**: `https://ellucian.atlassian.net/wiki/spaces/BANNER/pages/[api-security]`
- **SAML Configuration Guide**: `https://ellucian.atlassian.net/wiki/spaces/BANNER/pages/[saml-config]`

### **Internal Process Documentation**

- **Architecture Alignment Workshop Output**: `https://ellucian.atlassian.net/wiki/spaces/MTDLANDTL/pages/896270414/Sprint+0+Architecture+Alignment`
- **Discovery Workshop Templates**: `https://ellucian.atlassian.net/wiki/spaces/MTDLANDTL/pages/723355418`
- **Security Assessment Toolkit**: `https://ellucian.atlassian.net/wiki/spaces/SECURITY/pages/[assessment-tools]`

### **Testing and Validation Resources**

- **Banner Identity Test Procedures**: Based on institutional regression testing documentation
- **Performance Benchmarking Tools**: `https://ellucian.atlassian.net/wiki/spaces/PERFORMANCE/pages/[benchmarking]`
- **Security Validation Framework**: `https://ellucian.atlassian.net/wiki/spaces/SECURITY/pages/[validation]`

______________________________________________________________________

## 🎯 **Success Criteria**

**Technical Success Metrics** (from workshop requirements):

- Authentication success rate: > 99.5%
- API response time: < 3 seconds
- SSO login time: < 5 seconds
- LDAP query performance: < 500ms

**Business Success Metrics** (from stakeholder workshops):

- User adoption rate: > 95% within 30 days
- Help desk ticket reduction: > 50%
- Manual provisioning time reduction: > 80%
- Security incident rate: 0 critical incidents

**Compliance Success Metrics**:

- Audit trail completeness: 100%
- FERPA compliance validation: Pass
- Security penetration test: No critical vulnerabilities
- Access control documentation: Complete and approved

______________________________________________________________________

**This technical implementation guide provides the exact steps a technical architect would follow after workshop requirements are gathered, combining real institutional procedures with production-ready security configurations.**
