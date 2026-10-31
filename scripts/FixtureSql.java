import java.nio.charset.StandardCharsets;
import java.sql.DriverManager;

/** Read-only JSON query helper for the disposable local integration database. */
class FixtureSql {
    public static void main(String[] args) throws Exception {
        String sql = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        if (!sql.stripLeading().toUpperCase(java.util.Locale.ROOT).startsWith("SELECT ")) {
            throw new IllegalArgumentException("Only fixture SELECT queries are allowed");
        }
        try (var connection = DriverManager.getConnection(args[0], "bullbear", "")) {
            connection.setReadOnly(true);
            try (var statement = connection.createStatement()) {
                statement.setQueryTimeout(5);
                try (var rows = statement.executeQuery(sql)) {
                    if (!rows.next()) throw new IllegalStateException("Fixture row missing");
                    System.out.println(rows.getString(1));
                }
            }
        }
    }
}
